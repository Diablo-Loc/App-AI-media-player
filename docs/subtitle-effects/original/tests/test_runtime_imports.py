"""Fresh Python child checks with app/ on sys.path and no repository-root leak."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.runtime_import_contracts import before_import_changes
from tools.audit_runtime_imports import scan

ROOT = Path(__file__).resolve().parents[1]


class EntryImportTests(unittest.TestCase):
    def child(self, frozen=False):
        script = """
import ast, importlib.util, runpy, sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root/'app'))
assert importlib.util.find_spec('app') is None, sys.path
if sys.argv[2]=='frozen':
    sys.frozen=True
    sys._MEIPASS=str(Path.cwd()/'_internal')
    sys.executable=str(Path.cwd()/'BoTube.exe')
runpy.run_path(str(root/'app/run_app.py'),run_name='botube_import_smoke')
import ui.main_window, ui.pages.settings_dialog, download_core.download_worker
import download_core.download_options as policy
assert download_core.download_worker.build_download_command is policy.build_download_command
assert ui.pages.settings_dialog.QUALITIES is policy.QUALITIES
import download_core.download_source_app as resources
import control.ai_controller as controller
nodes=[n for n in ast.walk(ast.parse(Path(resources.__file__).read_text(encoding='utf-8-sig')))
       if isinstance(n,ast.ImportFrom) and any(a.name=='_set_resource_cache_state' for a in n.names)]
assert len(nodes)==5
for node in nodes:
    ns={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'cache-import','exec'),ns)
    assert ns['_set_resource_cache_state'] is controller._set_resource_cache_state
controller._set_resource_cache_state(True,True)
assert controller._get_resource_cache_state()=={'checked':True,'ready':True}
controller._set_resource_cache_state(False,False)
assert controller.AIWorker._is_ai_cached_ready is False
for legacy in ('from app.download_core.download_options import ORIGINAL',
               'from app.control.ai_controller import _set_resource_cache_state'):
    try:
        exec(legacy,{})
    except ModuleNotFoundError as error:
        assert error.name=='app'
    else:
        raise AssertionError('repo root leaked into isolated child')
assert 'app' not in sys.modules
assert 'app.download_core.download_options' not in sys.modules
print('ENTRY_AND_CACHE_IMPORT_OK')
"""
        with tempfile.TemporaryDirectory(prefix='botube-entry-import-') as directory:
            result = subprocess.run([sys.executable,'-I','-c',script,str(ROOT),'frozen' if frozen else 'direct'],
                cwd=directory, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8'),
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('ENTRY_AND_CACHE_IMPORT_OK',result.stdout)

    def test_direct_entry_without_repository_root_or_preview_stubs(self):
        self.child()

    def test_frozen_import_layout_without_repository_root(self):
        # Uses actual dependencies/imports but not a compiled EXE/Qt event loop.
        self.child(frozen=True)

    def test_all_local_imports_in_runtime_graph_resolve_statically(self):
        result = scan()
        self.assertGreater(result['source_count'],100)
        self.assertEqual(result['runtime_issues'],[])
        # A dormant historical placeholder still references the removed API.
        self.assertTrue(any(i['file']=='app/downloader.py' and 'models_dir' in i['issue']
                            for i in result['issues']))
        self.assertNotIn('downloader',result['runtime_reachable_modules'])


class ImportScopeTests(unittest.TestCase):
    def test_only_import_names_and_exact_source_gate_adapters_changed(self):
        manifest=json.loads((ROOT/'docs/runtime-imports/reviewed-sources.json').read_text(encoding='utf-8'))
        for relative in manifest:
            before=before_import_changes(relative)
            after=(ROOT/relative).read_text(encoding='utf-8-sig').replace('\r\n','\n')
            if relative in ('app/download_core/download_worker.py','app/ui/pages/settings_dialog.py'):
                self.assertEqual(after.replace('from download_core.download_options import',
                                                'from app.download_core.download_options import'),before)
            elif relative=='app/download_core/download_source_app.py':
                self.assertEqual(after.replace('from control.ai_controller import _set_resource_cache_state',
                    'from app.control.ai_controller import _set_resource_cache_state'),before)
            elif relative=='app/downloader.py':
                self.assertEqual(after.replace('from .paths import models_dir','from app.paths import models_dir'),before)
            elif relative=='tests/download_quality_contracts.py':
                self.assertEqual(after.replace('    from tests.runtime_import_contracts import before_import_changes\n'
                    '    current = before_import_changes(relative, raw=True)',
                    '    current = (ROOT / relative).read_bytes()'),before)
            elif relative=='tests/test_download_quality.py':
                self.assertEqual(after.replace('                from tests.runtime_import_contracts import before_import_changes\n'
                    '                current = before_import_changes(item[\'path\'], raw=True)',
                    '                current = (ROOT/item[\'path\']).read_bytes()'),before)
            else:
                self.fail('Unapproved import-phase source: '+relative)


if __name__=='__main__':
    unittest.main()
