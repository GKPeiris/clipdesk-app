"""Independent GTK process used by integration tests (synthetic data only)."""
import base64, json, sys
import gi
gi.require_version('Gtk','4.0'); gi.require_version('Gdk','4.0')
from gi.repository import Gtk,Gdk,GLib
Gtk.init()
clipboard=Gdk.Display.get_default().get_clipboard()
loop=GLib.MainLoop()
if sys.argv[1]=='provide':
    payload=json.loads(sys.stdin.readline())
    providers=[Gdk.ContentProvider.new_for_bytes(k,GLib.Bytes.new(base64.b64decode(v))) for k,v in payload.items()]
    clipboard.set_content(Gdk.ContentProvider.new_union(providers))
    print('READY',flush=True)
else:
    mime=sys.argv[2]
    def opened(cb,result):
        try:
            stream,actual=cb.read_finish(result)
            def read(source,res):
                try: print(base64.b64encode(source.read_bytes_finish(res).get_data()).decode(),flush=True)
                except Exception as error: print(str(error),file=sys.stderr)
                loop.quit()
            stream.read_bytes_async(8*1024*1024,0,None,read)
        except Exception as error:
            print(str(error),file=sys.stderr); loop.quit()
    def start_read():
        if not clipboard.get_formats().contain_mime_type(mime):
            return True
        clipboard.read_async([mime],0,None,opened)
        return False
    GLib.timeout_add(250,start_read)
GLib.timeout_add_seconds(20,lambda: (loop.quit(),False)[1])
loop.run()
