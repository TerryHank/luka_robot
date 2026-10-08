from . import source_checks


def test_build_and_installed_copies_do_not_count_as_product_source(tmp_path,monkeypatch):
    monkeypatch.setattr(source_checks,'ROOT',tmp_path)
    for directory in ('control/luka_base_gate','build/luka_base_gate','install/luka_base_gate','log'):
        path=tmp_path/directory/'driver.py'
        path.parent.mkdir(parents=True)
        path.write_text('import ddsm_car_control\n',encoding='utf-8')
    assert [path.relative_to(tmp_path).as_posix() for path in source_checks.sources(tmp_path)]==[
        'control/luka_base_gate/driver.py']
