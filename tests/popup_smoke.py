import tempfile,time,io
from PIL import Image
from clipdeck.app import ClipDeck,Gtk,GLib
app=ClipDeck(tempfile.mkdtemp(prefix='clipdeck-popup-'),app_id='io.github.clipdeck.PopupTest')
app.register(None)
context=GLib.MainContext.default()
def pump(seconds=.25):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while context.pending(): context.iteration(False)
        time.sleep(.005)
assert app.window is None and app.popup is None
text=app.store.add({'text/plain':b'Copied text'})
link=app.store.add({'text/plain':b'https://example.org'})
image=io.BytesIO(); Image.new('RGB',(160,80),'#a99cff').save(image,format='PNG')
image_id=app.store.add({'image/png':image.getvalue()})
app.store.add({'text/uri-list':b'file:///tmp/test.txt'})
app.store.add({'text/plain':b'Uncopied snippet'},copied=False)
app.show_popup(remember=False);pump()
assert app.window is None,'Popup must not create the full window'
assert set(app.popup.item_ids)=={text,link,image_id}
assert app.popup.get_visible()
app.show_popup(remember=False);assert not app.popup.get_visible()
app.activate();pump()
assert app.window.get_visible() and not app.popup.get_visible()
app.show_popup(remember=False);pump()
app.copy_item(text,from_popup=True);pump()
assert not app.popup.get_visible()
assert app.window.get_visible(),'Popup copy must leave full app open'
app.close_request();pump()
assert not app.window.get_visible()
app.present_popup();pump()
app.popup.key_pressed(None,65307,0,0);assert not app.popup.get_visible()
app.store.add({'text/plain':b'Background capture after windows close'})
app.show_popup(remember=False);pump()
assert len(app.popup.item_ids)==4
for window in list(Gtk.Window.get_toplevels()): window.destroy()
app.store.close()
print('PASS background startup, text/image-only popup, independent full view, toggle, copy, close and Escape')
