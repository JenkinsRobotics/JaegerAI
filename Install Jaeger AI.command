#!/bin/zsh
# Double-click to install or repair Jaeger AI on macOS.
cd "${0:A:h}"
print "=========================================="
print "       Welcome to Jaeger AI Installer     "
print "=========================================="
print ""
print "This will set up your local Jaeger AI agent, compile the native macOS"
print "menu bar app, and start your unified local/remote WebUI."
print ""
if bash install.sh --product; then
  print ""
  print "=========================================="
  print "✓ Installation Succeeded!"
  print "=========================================="
  print ""
  print "Local macOS App: Available in /Applications or run ./jaeger"
  print "Remote WebUI:    http://localhost:8790"
  print ""
  print "You can close this window now."
else
  print ""
  print "⚠️ Installation stopped. Review the message above, correct the issue,"
  print "and run this installer again."
fi
read "?Press Return to close this window."

