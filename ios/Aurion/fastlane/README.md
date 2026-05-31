fastlane documentation
----

# Installation

Make sure you have the latest version of the Xcode command line tools installed:

```sh
xcode-select --install
```

For _fastlane_ installation instructions, see [Installing _fastlane_](https://docs.fastlane.tools/#installing-fastlane)

# Available Actions

## iOS

### ios bootstrap

```sh
[bundle exec] fastlane ios bootstrap
```

Create App IDs + App Store Connect app record (one-time)

### ios upload_testflight

```sh
[bundle exec] fastlane ios upload_testflight
```

Build + upload to TestFlight (mirrors ios-testflight.yml)

### ios invite_pilot_physicians

```sh
[bundle exec] fastlane ios invite_pilot_physicians
```

Invite pilot physicians as TestFlight internal testers

### ios distribute_latest

```sh
[bundle exec] fastlane ios distribute_latest
```

Distribute the latest uploaded build (external group + internal auto-delivery)

### ios invite_internal_testers

```sh
[bundle exec] fastlane ios invite_internal_testers
```

Invite emails as ASC team members (Customer Support role) for internal-tester access

### ios add_to_pilot_internal

```sh
[bundle exec] fastlane ios add_to_pilot_internal
```

Add team members to the Pilot internal beta group

### ios list_groups

```sh
[bundle exec] fastlane ios list_groups
```

List beta groups + tester memberships

### ios list_testers

```sh
[bundle exec] fastlane ios list_testers
```

List current TestFlight testers

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
