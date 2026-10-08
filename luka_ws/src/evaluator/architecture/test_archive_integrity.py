import csv
import hashlib
from .source_checks import ROOT


def test_every_archived_source_or_fixture_preserves_its_bytes():
    manifest=ROOT/'docs/architecture/LEGACY_MOVES.tsv'
    with manifest.open(encoding='utf-8',newline='') as stream:
        rows=list(csv.DictReader(stream,delimiter='\t'))
    assert len(rows)==222
    for row in rows:
        assert not (ROOT/row['original_path']).exists(),row['original_path']
        archived=ROOT/row['archive_path']
        assert hashlib.sha256(archived.read_bytes()).hexdigest()==row['sha256'],row['archive_path']
    assert (ROOT/'common/legacy/COLCON_IGNORE').is_file()
