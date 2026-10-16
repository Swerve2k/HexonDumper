# Hexon

Dump and replace textures in DirectX 12 games on Windows.

Hexon watches the textures a game sends to your GPU, saves them as DDS files you can edit, and swaps your edited versions back in while the game runs. Each game gets its own profile with its own settings, dumps and replacements.

> **Only use Hexon with offline or unprotected games.** In games with anti-cheat (BattlEye, Easy Anti-Cheat and similar) it can get your account banned. Hexon warns you when it finds common anti-cheat files, but the decision is yours. You use Hexon at your own risk.

## Contents

- [What you need](#what-you-need)
- [Install Hexon](#install-hexon)
- [Quick start](#quick-start)
- [Add a game](#add-a-game)
- [Dump textures](#dump-textures)
- [Replace a texture](#replace-a-texture)
- [Mip chains](#mip-chains)
- [Settings](#settings)
- [Discord Rich Presence](#discord-rich-presence)
- [Updating, removing and moving Hexon](#updating-removing-and-moving-hexon)
- [Where Hexon keeps its files](#where-hexon-keeps-its-files)
- [Troubleshooting](#troubleshooting)

## What you need

- Windows 10 or 11, 64-bit
- A 64-bit **DirectX 12** game that runs without anti-cheat
- Optional: the Discord desktop app, for Rich Presence
- Optional: `texconv.exe`, if you want to replace textures with PNG or JPG images instead of DDS files

## Install Hexon

1. Download `Hexon-Setup-1.0.0.exe` from the Releases page.
2. Run it and follow the steps. It installs for your user by default, so no administrator rights are needed.
3. Start Hexon. The first time, read the notice and press **I understand**.

Windows may show a SmartScreen warning because the installer is new. Choose **More info**, then **Run anyway** if you downloaded it from the official Releases page.

## Quick start

1. Open Hexon and press **Add game…** (it opens automatically the first time).
2. Pick the game's `.exe` and let Hexon install into it.
3. Start the game the way you normally do.
4. Play for a minute. Open the **Textures** tab and watch the dumped textures appear.
5. Select one, press **Replace with file…**, choose your edited DDS or image.
6. Reload the map or menu in the game. Your texture shows up.

## Add a game

Each game you mod is a **profile**. Switch between them with the dropdown at the top of the window.

1. Press **Add game…**, or choose **+ Add game…** in the dropdown.
2. Select the game's main `.exe` inside its install folder. Use the game itself, not a launcher like Steam or Ubisoft Connect.
3. Hexon names the profile after the game. You can rename it on the **Profiles** tab.
4. Press **Install** when asked, or later on the Profiles tab.

What Install does: it adds a `dxgi.dll` file to the game's folder. That is how Hexon gets loaded when the game starts.

Things Hexon checks for you:

- **Another `dxgi.dll` already there** (for example from ReShade). Hexon asks before replacing it, keeps your original as `dxgi.dll.hexon-backup`, and puts it back when you uninstall Hexon from that game. The other mod will not work while Hexon is installed.
- **Anti-cheat files** in the game folder. Hexon warns you and lets you cancel.
- **32-bit games.** Hexon only supports 64-bit games and will refuse them.

You can only install or uninstall while the game is closed.

The Profiles tab also shows whether Hexon hooked DirectX 12 the last time the game ran. If it says the game never created a DirectX 12 device, you probably picked the wrong exe or the game is not DirectX 12.

## Dump textures

Start the game normally. Hexon saves every texture the game uploads as a `.dds` file in that game's `hexon\dump` folder.

On the **Textures** tab:

- **Filter** by hash, size or format (for example `BC7` or `2048`).
- **Sort** by newest, largest or name. Newest first is handy right after loading into a map.
- **Select** a texture to see a preview, its size, format and file size.
- New dumps appear while you play and your selection stays put.

Each mip level of a texture is dumped as its own file. The file name is `hash_widthxheight_format.dds`.

Dumping is limited by **Settings → Dump limit on this PC** (4 GB by default). The bar shows how much is used, and **Clear dump folder…** removes the dumps but keeps your replacements. Turn **Dump textures while the game runs** off once you have what you need, because dumping can make the game stutter.

## Replace a texture

A replacement takes effect the next time the game uploads that texture, usually after reloading a map or going back to a menu. Hexon notices new and changed replacement files within a few seconds, so you can keep the game running while you work.

### Option 1: replace with a DDS

The DDS must have the **same width, height and format** as the dumped texture. The Textures tab shows these, for example `2048x2048 BC7`. Sizes and formats that don't match are rejected with a message.

1. Select the texture in the **Textures** tab.
2. Press **Replace with file…** and pick your `.dds`.

Common DDS files from Paint.NET, GIMP and Photoshop work, as do DDS files with a DX10 header.

### Option 2: replace with a PNG or JPG

Hexon can convert an image for you, resizing it to the right size and format. This needs Microsoft's `texconv` tool:

1. Download `texconv.exe` from the DirectXTex releases on GitHub (`microsoft/DirectXTex`).
2. Put it in the Hexon install folder, or point to it under **Settings → Replacements → texconv**.
3. Select a texture, press **Replace with file…** and pick a PNG, JPG, TGA, BMP or TIFF.

### Option 3: drag and drop

- Drop one `.dds` or image onto the Hexon window to replace the selected texture.
- Drop several `.dds` files that are **named exactly like the dumped ones** and each goes to its own texture. This is the quickest way to apply a whole edited folder.

### Making a DDS by hand

```
texconv -f BC7_UNORM -m 0 -dx10 -y -o out my_edit.png
```

Use the same format name as the dump. For sRGB formats use `BC7_UNORM_SRGB` and add `-srgb`. `-m 0` builds a full mip chain, `-m 1` makes a single level.

### The Changed tab

Lists every texture you replaced, with thumbnails. Select one to compare **Original** and **Replacement** side by side, see how many mip levels the replacement has, or **Remove replacement**.

## Mip chains

Games draw smaller versions (mips) of a texture when it is far away. If your replacement DDS contains mip levels and its top level matches a texture, Hexon also replaces that texture's smaller levels, so it doesn't snap back to the original at a distance.

This is **experimental**. If a texture looks wrong, switch off **Settings → Replacements → Apply mip chains** and restart the game. Smaller mips that the game loaded before the top level can stay original until the texture is loaded again.

## Settings

Options marked *per game* apply to the profile you have selected.

| Setting | What it does |
|---|---|
| Dump textures while the game runs *(per game)* | Turns dumping on or off |
| Dump limit on this PC *(per game)* | Maximum size of the dump folder |
| Don't dump textures smaller than *(per game)* | Skips tiny textures when dumping. Replacements still work at any size |
| Apply replacements *(per game)* | Turns replacing on or off |
| Apply mip chains *(per game)* | See [Mip chains](#mip-chains) |
| texconv, generate mip chain | Image conversion options |
| Show texture previews, preview quality | Previews are made in the background at low priority and cached |
| Discord Rich Presence | See below |
| Show Log tab | Shows Hexon's log inside the app |
| Verbose logging in the game *(per game)* | Extra detail in `hexon.log`, for troubleshooting |

Game options are applied the next time the game starts.

## Discord Rich Presence

When the Discord desktop app is running, Hexon shows what you are doing as your activity. In **Settings → Discord Rich Presence** you choose what is shown:

- the game you are modding
- which tab you are on
- textures dumped and replaced
- dump disk usage
- whether the game is running
- time since Hexon opened

The image and button are fixed: the button always reads **Get Hexon** and links to the project page. You can set a different game name per profile on the Profiles tab. Use the first checkbox to switch Rich Presence off completely.

If nothing shows up in Discord, make sure the desktop app is running (not just the browser) and that **Share your detected activity** is on under Discord's Activity Privacy settings. The status line in Settings tells you what Hexon sees.

## Updating, removing and moving Hexon

**Update Hexon:** run the new installer over the old one. Then, for each game, open the Profiles tab and press **Update** (it appears when a newer DLL is available). Close the game first.

**Remove Hexon from one game:** Profiles tab, **Uninstall**. If Hexon replaced another `dxgi.dll`, your original comes back. Your dumps and replacements stay in the game's `hexon` folder.

**Delete a profile:** Profiles tab, **Delete profile…**. Hexon removes itself from that game first.

**Uninstall Hexon completely:** use Windows *Installed apps*. The uninstaller offers to remove Hexon from your games first (close them first) and to delete your profiles and settings.

**Game moved or reinstalled:** Profiles tab, **Change…** to point the profile at the new exe. Uninstall Hexon from the old location first.

## Where Hexon keeps its files

In each game folder:

| Path | Contents |
|---|---|
| `dxgi.dll` | Hexon's loader |
| `hexon\dump\` | Dumped textures |
| `hexon\replace\` | Your replacements |
| `hexon\hexon.ini` | The game's settings (written by the app) |
| `hexon\hexon.log` | Log from the last runs |

For the app itself, profiles are saved in `%APPDATA%\CELESTARR\Hexon\profiles.json`.

**Sharing a texture pack:** send someone the files in `hexon\replace`. They work for people whose game uses the same textures, because files are matched by their contents.

## Troubleshooting

**The game won't start after installing.** Uninstall Hexon from that game on the Profiles tab (or delete `dxgi.dll` from the game folder). Then check `hexon\hexon.log` and report the problem.

**Nothing gets dumped.** Look at the *Last launch* line on the Profiles tab. If Hexon never saw a DirectX 12 device, the exe or the game is wrong. Turn on **Show Log tab** and **Verbose logging**, restart the game, and read the log. Games that load textures through DirectStorage or GPU-side decompression may not be supported.

**My replacement doesn't show up.** The file name must match the dumped texture and have the same size and format. Reload the map or menu so the game uploads the texture again. Check that **Apply replacements** is on.

**Install or uninstall fails.** Close the game. If it lives in a protected folder such as `Program Files`, run Hexon as administrator.

**Antivirus complains.** Hexon loads a DLL into a game and hooks graphics calls, which looks suspicious to some security software. Only download Hexon from the official Releases page, and add an exception if you trust it.

**Previews are missing.** They need the helper that ships with Hexon. If you see an error where the preview should be, reinstall Hexon.

**Discord status is empty.** See [Discord Rich Presence](#discord-rich-presence).

**The game stutters.** Dumping reads a lot of texture data. Turn dumping off, or raise the minimum dump size, once you have the textures you need.

**Mip replacements look wrong.** Turn off **Apply mip chains** and restart the game.
