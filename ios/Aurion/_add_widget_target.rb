#!/usr/bin/env ruby
# One-shot script to add the AurionWidgets app-extension target.
# Run via `cd ios/Aurion && ruby _add_widget_target.rb`. Idempotent —
# bails if the target already exists.

require "xcodeproj"

PROJECT_PATH = "Aurion.xcodeproj"
WIDGET_NAME  = "AurionWidgets"
WIDGET_BUNDLE_ID = "com.aurionclinical.physician.widgets"
DEPLOYMENT_TARGET = "26.0"
DEVELOPMENT_TEAM  = "S5N6XHH7AQ"
SWIFT_VERSION = "5.0"

# Files in AurionWidgets/ that belong to the widget target.
WIDGET_LOCAL_FILES = %w[
  AurionWidgetsBundle.swift
  AurionCaptureActivityWidget.swift
  StartSessionWidget.swift
]

# Files outside AurionWidgets/ that the widget target also compiles
# (shared with the main app). Paths relative to project root.
SHARED_FILES = %w[
  Aurion/Session/AurionCaptureActivityAttributes.swift
]

project = Xcodeproj::Project.open(PROJECT_PATH)

if project.targets.any? { |t| t.name == WIDGET_NAME }
  puts "[skip] #{WIDGET_NAME} target already exists."
  exit 0
end

main_target = project.targets.find { |t| t.name == "Aurion" } ||
              (abort "could not find main Aurion target")

# --- 1. Enable Live Activities on the main app ---------------------------
main_target.build_configurations.each do |cfg|
  cfg.build_settings["INFOPLIST_KEY_NSSupportsLiveActivities"] = "YES"
end

# --- 2. Create the widget extension target -------------------------------
widget = project.new_target(
  :app_extension,
  WIDGET_NAME,
  :ios,
  DEPLOYMENT_TARGET,
  nil,        # default product reference
  :swift
)

widget.build_configurations.each do |cfg|
  bs = cfg.build_settings
  bs["PRODUCT_BUNDLE_IDENTIFIER"] = WIDGET_BUNDLE_ID
  bs["INFOPLIST_FILE"]            = "#{WIDGET_NAME}/Info.plist"
  bs["GENERATE_INFOPLIST_FILE"]   = "NO"
  bs["SWIFT_VERSION"]             = SWIFT_VERSION
  bs["IPHONEOS_DEPLOYMENT_TARGET"] = DEPLOYMENT_TARGET
  bs["TARGETED_DEVICE_FAMILY"]    = "1,2"
  bs["CODE_SIGN_STYLE"]           = "Automatic"
  bs["DEVELOPMENT_TEAM"]          = DEVELOPMENT_TEAM
  bs["MARKETING_VERSION"]         = "1.0"
  bs["CURRENT_PROJECT_VERSION"]   = "1"
  bs["SKIP_INSTALL"]              = "YES"
  bs["MACH_O_TYPE"]               = "mh_execute"   # widget extension is a mini-binary
  bs["LD_RUNPATH_SEARCH_PATHS"]   = "$(inherited) @executable_path/Frameworks @executable_path/../../Frameworks"
end

# --- 3. Add a project group for AurionWidgets + reference its sources ----
widget_group = project.main_group.new_group(WIDGET_NAME, WIDGET_NAME)

WIDGET_LOCAL_FILES.each do |fname|
  ref = widget_group.new_reference(fname)
  widget.source_build_phase.add_file_reference(ref)
end

# Add a reference for the Info.plist (so Xcode shows it in the navigator),
# but don't include it in any build phase — the build setting points at it.
widget_group.new_reference("Info.plist")

# --- 4. Add shared files (live in Aurion/, also compiled into widget) ----
SHARED_FILES.each do |path|
  # Find or create a PBXFileReference at this path within the existing
  # tree. Synchronized groups don't expose individual file refs, so we
  # create a NEW reference rooted at the project's main group. This is
  # safe — multiple PBXFileReference instances can point at the same
  # filesystem path; Xcode dedupes by URL at build time.
  ref = project.main_group.new_reference(path)
  widget.source_build_phase.add_file_reference(ref)
end

# --- 5. Embed the appex into the main app -------------------------------
# Create a "Copy Files" build phase on the main target with dstSubfolderSpec
# = 13 (Plug-Ins / Extensions). This is what Xcode does when you tick the
# "Embed App Extensions" checkbox in the General tab.
embed = main_target.new_copy_files_build_phase("Embed App Extensions")
embed.symbol_dst_subfolder_spec = :plug_ins
embed.dst_path = ""
appex_ref = widget.product_reference
build_file = embed.add_file_reference(appex_ref)
build_file.settings = { "ATTRIBUTES" => ["RemoveHeadersOnCopy"] }

# --- 6. Target dependency so widget builds before main embedding step ----
main_target.add_dependency(widget)

# --- 7. Save -------------------------------------------------------------
project.save
puts "[ok] added #{WIDGET_NAME} target"
puts "     bundle id : #{WIDGET_BUNDLE_ID}"
puts "     deployment: iOS #{DEPLOYMENT_TARGET}"
puts "     team      : #{DEVELOPMENT_TEAM}"
puts "     sources   : #{WIDGET_LOCAL_FILES.join(", ")}"
puts "     shared    : #{SHARED_FILES.join(", ")}"
