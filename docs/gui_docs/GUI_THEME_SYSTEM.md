# GUI Theme System

The GUI theme system is a GUI-owned presentation layer for Leonardo V2.
It provides validated theme tokens and stylesheet generation without changing
window identity, action identity, roadmap metadata, Core behavior, or domain
suite behavior.

## Ownership

GUI owns theme profiles, theme validation, and stylesheet generation. Themes
are data/configuration only. They may affect presentation, but they do not own
runtime state, service lifecycle, provider/API behavior, storage, chart logic,
analysis logic, trading behavior, or Runtime Manager controls.

`AGENTS.md` remains the implementation-agent authority. The Rick protocol
governs the Rick-side workflow around task shaping and package validation.

## Active Theme

The current default theme is:

```text
theme_id: leonardo_jarvish_cockpit
display_name: Leonardo Jarvish Cockpit
```

The theme defines a dark cockpit presentation using graphite surfaces, readable
text, and restrained cyan, teal, and blue accents. It is a baseline style
profile, not a window redesign.

## Token Groups

Every shipped theme must provide these groups:

- `identity`
- `colors`
- `typography`
- `spacing`
- `radius`
- `effects`
- `components`

The required component token groups are:

- `button`
- `panel`
- `card`
- `table`
- `tab`
- `status_chip`
- `input`

Missing required tokens fail during theme loading. Unknown top-level behavior
fields are not part of the supported theme contract.

## Boundaries

Themes must not:

- define GUI object IDs;
- define GUI action IDs;
- mutate GUI roadmap metadata;
- import Core, domain, provider, storage, chart, analysis, or trading modules;
- call network APIs;
- write storage;
- construct windows;
- start Core lifecycle;
- enter the Qt event loop;
- encode suite-specific business behavior.

The stylesheet applier requires only a target object exposing
`setStyleSheet(str)`. The theme system does not own `QApplication` creation,
window construction, or GUI startup lifecycle. The minimal GUI runner consumes
the default theme after creating or reusing `QApplication` and before window
composition, keeping theme application inside the GUI startup boundary.

## Future Themes

Future themes should be added as one static JSON profile and one explicit
registry entry. They should reuse the same token groups unless a separate phase
updates the theme contract, tests, and documentation together.

## Current Non-Goals

This system does not redesign the Main Window, Runtime Manager, Settings
Inspector, or suite windows. Task 0003 and later GUI design phases may consume
the theme tokens when changing window layouts and visual composition.
