import hashlib,io,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import seed
class FocusedBundleExpansion(unittest.TestCase):
 def fixture(self,d):
  records=[]
  with tarfile.open(d/'source.tar','w')as t:
   for name,body in [('needed.deb',b'needed'),('unrelated.deb',b'large unrelated package')]:
    info=tarfile.TarInfo(name);info.size=len(body);t.addfile(info,io.BytesIO(body));records.append(dict(file=name,sha256=hashlib.sha256(body).hexdigest()))
  return dict(packages=records)
 def test_selected_only_materializes_and_hashes_needed_payload(self):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);inv=self.fixture(d);seed.expand_bundles(d,inv,{'needed.deb'});self.assertEqual((d/'needed.deb').read_bytes(),b'needed');self.assertFalse((d/'unrelated.deb').exists())
 def test_dependency_free_root_copies_no_payload(self):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);inv=self.fixture(d)
   with patch.object(seed.shutil,'copyfileobj',side_effect=AssertionError('Unselected payload copied')):seed.expand_bundles(d,inv,set())
   self.assertEqual(list(d.glob('*.deb')),[])
 def test_selected_digest_mismatch_fails_and_cleans_partial(self):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);inv=self.fixture(d);inv['packages'][0]['sha256']='0'*64
   with self.assertRaisesRegex(ValueError,'hash differs'):seed.expand_bundles(d,inv,{'needed.deb'})
   self.assertFalse((d/'needed.deb').exists());self.assertFalse(list(d.glob('*.seed-partial')))
 def test_even_unselected_unsafe_member_is_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp)
   with tarfile.open(d/'unsafe.tar','w')as t:
    info=tarfile.TarInfo('../escape.deb');info.size=1;t.addfile(info,io.BytesIO(b'x'))
   with self.assertRaisesRegex(ValueError,'unsafe'):seed.expand_bundles(d,dict(packages=[]),set())
