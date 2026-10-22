import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from clipdeck.store import Store, MAX_ITEM, decode_formats, encode_formats, plain_html


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.settings['retention'] = 0

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, text, **kwargs):
        return self.store.add({'text/plain': text.encode()}, **kwargs)

    def test_duplicate_preserves_pin_and_updates_recency(self):
        a = self.add('hello', pinned=True, title='Greeting', now=10)
        b = self.add('hello', now=20)
        self.assertEqual(a,b)
        row = self.store.get(a)
        self.assertEqual((row['pinned'],row['title'],row['created'],row['used']), (1,'Greeting',10,20))

    def test_multiformat_round_trip(self):
        formats = {'text/plain': b'hello', 'text/html': b'<b>hello</b>'}
        a = self.store.add(formats)
        self.assertEqual(decode_formats(self.store.get(a)['payload']),formats)

    def test_literal_search_and_type_filter(self):
        a = self.add('100% done_ now')
        self.add('100x doneX now')
        self.add('https://example.org')
        self.assertEqual([r['id'] for r in self.store.list('%')], [a])
        self.assertEqual(len(self.store.list('_')),1)
        self.assertEqual(len(self.store.list(kind='link')),1)

    def test_limits_preserve_pins(self):
        self.store.settings['limit'] = 2
        pinned = self.add('keep', pinned=True)
        for i in range(5): self.add(str(i))
        self.assertEqual(len(self.store.list()),3)
        self.assertIsNotNone(self.store.get(pinned))

    def test_retention_preserves_pins(self):
        self.add('old', now=time.time()-3*86400)
        self.add('old pinned', pinned=True, now=time.time()-3*86400)
        self.store.settings['retention']=1
        self.store.prune()
        self.assertEqual(len(self.store.list()),1)
        self.assertTrue(self.store.list()[0]['pinned'])

    def test_clear_and_delete(self):
        a = self.add('pinned',pinned=True)
        self.add('ordinary')
        self.store.clear()
        self.assertEqual(len(self.store.list()),1)
        self.store.delete(a)
        self.assertEqual(len(self.store.list()),0)
        self.add('again',pinned=True)
        self.store.clear(True)
        self.assertEqual(len(self.store.list()),0)

    def test_export_import_preserves_content(self):
        self.add('hello 😃',pinned=True,title='Emoji greeting')
        path = Path(self.tmp.name)/'backup.json'
        self.assertEqual(self.store.export_file(path),1)
        self.store.clear(True)
        self.assertEqual(self.store.import_file(path),1)
        row=self.store.list()[0]
        self.assertEqual((row['preview'],row['title'],row['pinned']),('hello 😃','Emoji greeting',1))
        self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_invalid_import_is_atomic(self):
        self.add('existing')
        path=Path(self.tmp.name)/'bad.json'
        path.write_text(json.dumps({'format':'clipdeck','version':1,'items':[
            {'payload':encode_formats({'text/plain':b'valid'}),'pinned':False,'title':''},
            {'payload':{'text/plain':'not base64!'},'pinned':False,'title':''}]}))
        with self.assertRaises(ValueError): self.store.import_file(path)
        self.assertEqual([r['preview'] for r in self.store.list()],['existing'])

    def test_reject_oversized_and_unknown_data(self):
        for data in [{'text/plain':b'x'*(MAX_ITEM+1)}, {'application/x-shellscript':b'code'}, {'image/png':b'bad'}, {'text/plain':b'\xff'}, {}]:
            with self.assertRaises((ValueError,UnicodeError)): self.store.add(data)
        self.assertEqual(len(self.store.list()),0)

    def test_private_database_and_settings(self):
        self.store.save_settings()
        self.assertEqual(Path(self.tmp.name).stat().st_mode & 0o777,0o700)
        for name in ['history.sqlite3','settings.json']:
            self.assertEqual((Path(self.tmp.name)/name).stat().st_mode & 0o777,0o600)

    def test_settings_survive_restart(self):
        self.store.settings['paused']=True
        self.store.save_settings()
        other=Store(self.tmp.name)
        self.assertTrue(other.settings['paused']); other.close()

    def test_html_is_plain_preview(self):
        self.assertEqual(plain_html('<p>Hello &amp; world</p><script>bad()</script>'),'Hello & world')
        a=self.store.add({'text/html':b'<b>hello</b>'})
        self.assertEqual(self.store.get(a)['preview'],'hello')

    def test_files_and_image_classification(self):
        a=self.store.add({'text/uri-list':b'#comment\r\nfile:///tmp/a.txt\r\n'})
        self.assertEqual(self.store.get(a)['kind'],'files')
        self.assertEqual(self.store.get(a)['preview'],'file:///tmp/a.txt')

    def test_export_refuses_symlinks(self):
        target=Path(self.tmp.name)/'keep.txt'; target.write_text('keep')
        link=Path(self.tmp.name)/'export.json'; link.symlink_to(target)
        with self.assertRaises(OSError): self.store.export_file(link)
        self.assertEqual(target.read_text(),'keep')

    def test_compact_history_contains_only_copied_text_and_images(self):
        text=self.add('copied text')
        link=self.add('https://example.org')
        snippet=self.store.add({'text/plain':b'not copied yet'},pinned=True,title='Snippet',copied=False)
        self.store.add({'text/uri-list':b'file:///tmp/file.txt'})
        self.assertEqual({r['id'] for r in self.store.clipboard_items()},{text,link})
        self.store.add({'text/plain':b'not copied yet'})
        self.assertIn(snippet,{r['id'] for r in self.store.clipboard_items()})

    def test_export_preserves_uncopied_snippets(self):
        self.store.add({'text/plain':b'snippet'},copied=False)
        path=Path(self.tmp.name)/'backup.json'
        self.store.export_file(path)
        self.store.clear(True)
        self.store.import_file(path)
        self.assertEqual(self.store.clipboard_items(),[])
        self.assertEqual(len(self.store.list()),1)

if __name__=='__main__': unittest.main()
