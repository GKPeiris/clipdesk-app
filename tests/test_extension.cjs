// Isolated API mocks verify bridge logic; this is not a live GNOME Shell test.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
let offered = {}, calls = [], timers = new Map(), timerId = 0, selectedHandler;
let disconnected = false, removed = false, destroyed = false, unexported = false;
const keys=[];
const target={get_wm_class:()=> 'Editor', activate:()=> {sandbox.global.display.focus_window=target;}};
const sandbox = {
    console, TextDecoder, TextEncoder,
    St:{Clipboard:{get_default:()=>({get_mimetypes:()=>Object.keys(offered),get_content:(_t,mime,cb)=>cb(null,{get_size:()=>offered[mime].length,get_data:()=>offered[mime]})})},ClipboardType:{CLIPBOARD:1},Icon:class{}},
    Meta:{SelectionType:{SELECTION_CLIPBOARD:1},KeyBindingFlags:{NONE:0}},
    Shell:{ActionMode:{NORMAL:1}},
    Clutter:{get_default_backend:()=>({get_default_seat:()=>({create_virtual_device:()=>({notify_keyval:(_time,key,state)=>keys.push([key,state])})})}),InputDeviceType:{KEYBOARD_DEVICE:1},KEY_Control_L:1,KEY_v:2,KeyState:{PRESSED:1,RELEASED:0}},
    Gio:{DBus:{session:{call:(dest,path,iface,method,value,_r,flags,_t,_c,done)=>{calls.push({method,value,flags});done({call_finish:()=>{}},{});}}},DBusCallFlags:{NONE:0,NO_AUTO_START:1},DBusExportedObject:{wrapJSObject:()=>({export:()=>{},unexport:()=>{unexported=true;}})}},
    GLib:{PRIORITY_DEFAULT:0,SOURCE_CONTINUE:true,SOURCE_REMOVE:false,timeout_add_seconds:(_p,_s,fn)=>{timers.set(++timerId,fn);return timerId;},timeout_add:(_p,_s,fn)=>{timers.set(++timerId,fn);return timerId;},Source:{remove:id=>timers.delete(id)},Variant:class{constructor(type,value){this.type=type;this.value=value;}},base64_encode:bytes=>Buffer.from(bytes).toString('base64'),get_monotonic_time:()=>1000000},
    Extension:class{getSettings(){return {}; } get uuid(){return 'test';}},
    Main:{wm:{addKeybinding:()=>{},removeKeybinding:()=>{removed=true;}},panel:{addToStatusArea:()=>{}}},
    PanelMenu:{Button:class{constructor(){this.menu={addMenuItem:()=>{}};}add_child(){}destroy(){destroyed=true;}}},
    PopupMenu:{PopupMenuItem:class{connect(){}}},
    global:{display:{get_selection:()=>({connect:(_s,fn)=>{selectedHandler=fn;return 1;},disconnect:()=>{disconnected=true;}}),focus_window:target},get_window_actors:()=>[{meta_window:target}],get_current_time:()=>1},
};
let source=fs.readFileSync(path.join(__dirname,'../extension/extension.js'),'utf8');
source=source.replace(/^import .*;\n/gm,'').replace('export default class','globalThis.TestClass = class');
vm.runInNewContext(source,sandbox);
const ext=new sandbox.TestClass();ext.enable();
assert.equal(calls[0].method,'Heartbeat');
assert.equal(calls[0].flags,1);
calls=[];
offered={'text/plain':Buffer.from('hello'),'text/html':Buffer.from('<b>hello</b>')};
selectedHandler(null,1);
assert.equal(calls.length,1);assert.equal(calls[0].method,'Capture');
const payload=JSON.parse(calls[0].value.value[0]);
assert.equal(Buffer.from(payload['text/plain'],'base64').toString(),'hello');
assert.equal(Buffer.from(payload['text/html'],'base64').toString(),'<b>hello</b>');
calls=[];
offered={'x-special/gnome-copied-files':Buffer.from('cut\nfile:///tmp/example.txt')};
selectedHandler(null,1);
assert.equal(Buffer.from(JSON.parse(calls[0].value.value[0])['text/uri-list'],'base64').toString(),'file:///tmp/example.txt');
calls=[];
offered={'text/plain':Buffer.from('secret'),'x-kde-passwordManagerHint':Buffer.from('secret')};
selectedHandler(null,1);assert.equal(calls.length,0);
offered={'text/plain':Buffer.alloc(8*1024*1024+1)};
selectedHandler(null,1);assert.equal(calls.length,0);
ext._show();assert.equal(calls[0].method,'ShowPopup');assert.equal(calls[0].flags,0);
let pasted=false;
ext.PasteAsync(null,{return_value:()=>{pasted=true;},return_dbus_error:()=>assert.fail('unexpected paste error')});
for(const [id,fn] of timers){if(id!==ext._heartbeat)fn();}
assert.ok(pasted);assert.equal(keys.length,4);
assert.deepEqual(keys,[[1,1],[2,1],[2,0],[1,0]]);
let noTarget=false;
ext.PasteAsync(null,{return_dbus_error:()=>{noTarget=true;}});assert.ok(noTarget);
ext.disable();assert.ok(disconnected&&destroyed&&unexported);
assert.equal(timers.has(ext._heartbeat),false);
console.log('PASS extension forwarding, sensitive marker exclusion, size bound, shortcut, paste target and lifecycle cleanup (mock APIs)');
