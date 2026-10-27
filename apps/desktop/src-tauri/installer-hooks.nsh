; Tauri NSIS hooks for Bayle (docs/decisions/0016-identity-and-updater.md).
; An update copies the new files over the old install and never deletes files the new version left out, so a stale
; engine file from an older release could stay. The bundled engine is replaced whole instead. Nothing outside $INSTDIR
; is touched; the state folder is elsewhere (app_local_data_dir).
!macro NSIS_HOOK_PREINSTALL
  RMDir /r "$INSTDIR\engine"
!macroend
