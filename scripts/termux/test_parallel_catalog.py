import copy
import json
from pathlib import Path
import tempfile
import tarfile
import io
import unittest

from parallel_catalog import merge
from seed import digest, expand_bundles


class MergeTests(unittest.TestCase):
    def test_lane_bundle_expands_only_hash_pinned_regular_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            content=b"exact archive fixture"
            import hashlib
            inventory=dict(packages=[dict(file="example_1_all.deb",sha256=hashlib.sha256(content).hexdigest())])
            with tarfile.open(root/"packages.tar","w") as archive:
                entry=tarfile.TarInfo("example_1_all.deb");entry.size=len(content)
                archive.addfile(entry,io.BytesIO(content))
            expand_bundles(root,inventory)
            self.assertEqual(content,(root/"example_1_all.deb").read_bytes())
            expand_bundles(root,inventory)
            (root/"example_1_all.deb").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError,"differs"):
                expand_bundles(root,inventory)

    def test_lane_bundle_rejects_aliases_and_namespace_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,kind in [("../escape.deb",tarfile.REGTYPE),("example_1_all.deb",tarfile.SYMTYPE)]:
                with tarfile.open(root/"packages.tar","w") as archive:
                    entry=tarfile.TarInfo(name);entry.type=kind;entry.linkname="/etc/passwd"
                    archive.addfile(entry)
                with self.assertRaisesRegex(ValueError,"unsafe"):
                    expand_bundles(root,dict(packages=[dict(file="example_1_all.deb",sha256="0"*64)]))

    def candidate(self, directory, recipes, payload=b"hash-pinned fixture"):
        directory.mkdir()
        plan=dict(identity="same-graph",configuration=dict(lock={},source={},patches=[]),
                  recipes={n:dict(path="packages/"+n,dependencies=[],initial_status="pending") for n in "abc"})
        records=[]
        for name in recipes:
            archive=directory/(name+"_1_all.deb")
            archive.write_bytes(payload)
            records.append(dict(file=archive.name,original_file=archive.name,recipe=name,sha256=digest(archive),control="fixture"))
        values=[dict(packages=records),dict(identity=["same-graph","runner"],recipes={n:dict(status="built" if n in recipes else "pending") for n in "abc"}),plan]
        pins=[]
        for name,value in zip(["inventory.json","catalog-ledger.json","catalog-plan.json"],values):
            path=directory/name;path.write_text(json.dumps(value));pins.append(digest(path))
        return [str(directory),*pins]

    def test_merge_counts_unique_outputs_and_retains_input_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            inputs=[self.candidate(root/"lane0","ab"),self.candidate(root/"lane1","bc")]
            ledger,inventory=merge(inputs,root/"union")
            self.assertEqual(3,len(inventory["packages"]))
            self.assertEqual(2,len(inventory["source_candidates"]))
            self.assertTrue(all(e["status"]=="built" for e in ledger["recipes"].values()))

    def test_conflicting_outputs_and_unpinned_metadata_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            first=self.candidate(root/"lane0","a")
            second=self.candidate(root/"lane1","a",b"different build bytes")
            with self.assertRaisesRegex(ValueError,"Conflicting"):
                merge([first,second],root/"union")
            self.assertFalse((root/"union").exists())
            first[1]="0"*64
            with self.assertRaises(ValueError):
                merge([first],root/"union")

    def test_explicit_compatible_parent_preference_retains_alternate_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            first=self.candidate(root/"lane0","a",b"first own-source build")
            second=self.candidate(root/"lane1","a",b"independent own-source build")
            _,inventory=merge([first,second],root/"union",prefer_first_compatible=True)
            self.assertEqual(1,len(inventory["packages"]))
            self.assertEqual(1,len(inventory["alternate_builds"]))
            self.assertEqual(b"first own-source build",(root/"union/a_1_all.deb").read_bytes())


if __name__=="__main__":
    unittest.main()
