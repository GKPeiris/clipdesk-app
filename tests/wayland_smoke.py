"""Native Wayland UI and self-owned clipboard check; does not test the extension."""
import os
os.environ['GDK_BACKEND']='wayland'
import tempfile,time
from clipdeck.app import ClipDeck, Gtk, Gdk, GLib
app=ClipDeck(tempfile.mkdtemp(prefix='clipdeck-wayland-'),app_id='io.github.clipdeck.WaylandTest')
app.register(None);app.activate()
context=GLib.MainContext.default()
def pump(duration=.5):
    end=time.monotonic()+duration
    while time.monotonic()<end:
        while context.pending(): context.iteration(False)
        time.sleep(.005)
pump()
assert 'Wayland' in Gdk.Display.get_default().__class__.__name__
app.store.settings['hide_after_copy']=False
app.copy_formats({'text/plain':b'Wayland local clipboard test'})
pump()
result=[]
def read(cb,res): result.append(cb.read_text_finish(res))
app.monitor.clipboard.read_text_async(None,read)
pump()
assert result==['Wayland local clipboard test'],result
app.change_tab('Pinned');pump(.1)
app.change_tab('Emoji & symbols');pump(.1)
app.change_tab('History');pump(.1)
app.settings_window();pump(.2)
for window in list(Gtk.Window.get_toplevels()): window.destroy()
app.store.close()
print('PASS native Wayland window, tabs, preferences and self-owned text clipboard')
