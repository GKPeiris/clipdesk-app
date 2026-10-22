"""Run on a desktop: exercise real GTK UI and cross-process clipboard exchange."""
import base64, io, json, os
from pathlib import Path
import subprocess, sys, tempfile, time
from PIL import Image
from clipdeck.app import ClipDeck, Gtk, GLib
from clipdeck.store import encode_formats

peer=Path(__file__).with_name('clipboard_peer.py')
os.environ['GDK_BACKEND']='x11'
app=ClipDeck(tempfile.mkdtemp(prefix='clipdeck-test-'), app_id='io.github.clipdeck.Test')
app.register(None); app.activate()
app.store.settings['hide_after_copy']=False
context=GLib.MainContext.default()

def pump(duration=.3):
    until=time.monotonic()+duration
    while time.monotonic()<until:
        while context.pending(): context.iteration(False)
        time.sleep(.005)

def wait_for(predicate, timeout=5):
    deadline=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>deadline: raise AssertionError('Timed out waiting for clipboard')
        pump(.05)

def provide(formats):
    proc=subprocess.Popen([sys.executable,str(peer),'provide'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    proc.stdin.write(encode_formats(formats)+'\n'); proc.stdin.flush()
    assert proc.stdout.readline().strip()=='READY'
    pump(.5)
    return proc

def read(mime):
    proc=subprocess.Popen([sys.executable,str(peer),'read',mime],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    wait_for(lambda: proc.poll() is not None)
    output,error=proc.communicate()
    assert proc.returncode==0,error
    assert output.strip(), error
    return base64.b64decode(output.strip())

def descendants(widget):
    yield widget
    child=widget.get_first_child()
    while child:
        yield from descendants(child)
        child=child.get_next_sibling()

try:
    p=provide({'text/plain':b'Clipboard integration test','text/html':b'<b>Clipboard integration test</b>'})
    wait_for(lambda: len(app.store.list())==1)
    row=app.store.list()[0]
    assert row['preview']=='Clipboard integration test'
    app.copy_item(row['id']); pump()
    assert read('text/plain')==b'Clipboard integration test'
    assert read('text/html')==b'<b>Clipboard integration test</b>'
    app.copy_item(row['id'],plain=True); pump()
    assert read('text/plain')==b'Clipboard integration test'
    p.terminate(); p.wait(); pump()
    print('PASS cross-process text + rich text capture and restore')
    app.store.settings['paused']=True
    n=len(app.store.list())
    p=provide({'text/plain':b'not saved while paused'}); assert len(app.store.list())==n
    p.terminate(); p.wait(); pump(); app.store.settings['paused']=False
    p=provide({'text/plain':b'private marker','application/x-keepassxc-clipboard':b'secret'}); assert len(app.store.list())==n, [r['preview'] for r in app.store.list()]
    p.terminate(); p.wait()
    print('PASS pause and password-manager exclusion')
    data=io.BytesIO(); Image.new('RGB',(300,120),'#8b79f0').save(data,format='PNG')
    png=data.getvalue()
    p=provide({'image/png':png}); wait_for(lambda: bool(app.store.list(kind='image')))
    image_id=app.store.list(kind='image')[0]['id']
    app.copy_item(image_id); pump(); assert read('image/png')==png
    p.terminate(); p.wait(); pump()
    print('PASS PNG capture, preview and restore')
    uris=b'file:///tmp/clipdeck-test.txt\r\n'
    p=provide({'text/uri-list':uris}); wait_for(lambda: bool(app.store.list(kind='files')))
    file_id=app.store.list(kind='files')[0]['id']
    app.copy_item(file_id); pump(); assert read('text/uri-list')==uris
    p.terminate(); p.wait(); pump()
    print('PASS file-reference capture and restore')
    p=provide({'x-special/gnome-copied-files':b'cut\nfile:///tmp/gnome-test.txt\n'}); wait_for(lambda: bool(app.store.list('gnome-test.txt')))
    assert app.store.list('gnome-test.txt')[0]['kind']=='files'
    p.terminate(); p.wait(); pump()
    print('PASS GNOME file-cut references restored non-destructively')
    app.pin(file_id); app.change_tab('Pinned'); pump()
    assert app.visible_ids==[file_id]
    app.change_tab('Emoji & symbols'); pump()
    assert '56' in app.count_label.get_text()
    app.change_tab('History'); app.search.set_text('Clipboard integration'); pump()
    assert app.visible_ids
    app.search.set_text(''); pump()
    app.new_snippet(); pump()
    dialog=next(w for w in Gtk.Window.get_toplevels() if w.get_title()=='New snippet')
    widgets=list(descendants(dialog))
    next(w for w in widgets if isinstance(w,Gtk.TextView)).get_buffer().set_text('Reusable snippet from GUI test')
    next(w for w in widgets if isinstance(w,Gtk.Button) and w.get_label()=='Save snippet').emit('clicked')
    pump(); assert app.store.list('Reusable snippet')[0]['pinned']
    print('PASS pinning, search, emoji and snippet editor')
    app.settings_window(); pump()
    settings=next(w for w in Gtk.Window.get_toplevels() if w.get_title()=='ClipDeck preferences')
    settings.close()
    app.confirm_clear(); pump()
    dialog=next(w for w in Gtk.Window.get_toplevels() if w.get_title()=='Clear clipboard history')
    next(w for w in descendants(dialog) if isinstance(w,Gtk.Button) and w.get_label()=='Cancel').emit('clicked')
    pump(); print('PASS preferences and clear confirmation')
    print('ALL GUI CHECKS PASSED')
finally:
    for w in list(Gtk.Window.get_toplevels()): w.destroy()
    app.store.close()
