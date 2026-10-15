# Hexon

Dump and replace textures in DirectX 12 games on Windows.

Hexon watches the textures a game uploads to your GPU, saves them as DDS files you can edit, and swaps your edited versions back in while the game runs.

## Features

- A profile per game, each with its own exe, dumps, replacements and settings
- Browse and preview every texture the game uses, with a Changed tab for what you replaced
- Replace with a DDS, or drop in a PNG or JPG and let Hexon convert it
- Mip chain support, dump size limit, live updates while you play
- Discord Rich Presence with options for what to show

## Install

Download the installer from the Releases page and run it. Add your game in Hexon, press Install, then launch the game as usual.

## Safety

Hexon adds a `dxgi.dll` to the game folders you choose. If one is already there, Hexon asks first, keeps a backup and restores it when you uninstall.

Only use Hexon with offline or unprotected games. In games with anti-cheat it can get your account banned. Hexon warns you when it finds common anti-cheat files in a game folder.

Hexon supports 64-bit DirectX 11 and 12 games, with partial DX10 support.
