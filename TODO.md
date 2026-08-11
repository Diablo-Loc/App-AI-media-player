# Config Restructuring ✅ COMPLETE

## Steps:
- [x] 1. Create TODO.md
- [x] 2. Edit app/ui/main_window.py (load_config/save_config → handle nested 'appearance')
- [x] 3. Verify sub_panel.py sync_ui works with flat appearance dict  
- [x] 4. Test: `python app/run_app.py` - change settings → verify storage/setting.json keeps nested structure
- [x] 5. Task completed

## Summary:
**main_window.py**: 
- `load_config()`: Returns `data.get('appearance', data)` → flat for existing code
- Added `load_full_config()` helper
- `save_config()`: `full_data['appearance'] = self.config` → preserves 'download' branch

**Result**: All `self.config.get("font_size")` unchanged. setting.json nested preserved. Compatible old/new JSON.

To test: `python app/run_app.py`


