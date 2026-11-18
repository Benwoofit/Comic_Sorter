# Comic Sorter

A small Windows app that sorts a folder of comics into a clean library:

```
Sorted Library/
    DC Batman/
        Vol. 02/
            Death of the Family/
                DC Batman Vol. 02 #003 - Death of the Family (2012).cbz
    Wolverine/
        Old Man Logan/
            Part 2/
                Wolverine - Old Man Logan - Part 2.cbz
    2000AD/
        2000AD #1234.cbz
```

Folders are `Series / Vol. NN / Subtitle`, plus an `Arc` folder inside when the filename gives one.
A level is only made when the filename gives that part:

- **no volume** in the name -> no `Vol.` folder and no "Vol." in the title
  (`Batman #001.cbz` -> `Batman/Batman #001.cbz`, `2000AD prog 1234.cbz` -> `2000AD/2000AD #1234.cbz`).
- **no subtitle** -> no subtitle folder, and nothing is ever called "No Subtitle"
  (`Batman/Vol. 01/Batman Vol. 01 #001.cbz`).

The file keeps a full title: `Series [Vol. NN] [#issue] [Ed. NNN] [- Subtitle] [- Arc] [(date)]`.

It reads each filename for **series**, **volume**, **issue #** and **subtitle / arc name**,
shows you the whole plan in a table first, and only then copies or moves the files.

## Branding
The window shows the **GW 2026** logo in the top-left corner, and the same logo is the window and
taskbar icon. The image lives in `assets/gw_logo.png` (replace it to change the logo), and the
`.exe` is built with it embedded so the logo still shows when the exe is moved on its own.
To change the text beside the logo, edit `APP_TITLE_TEXT` near the top of `comic_sorter.py`.

## Run it

A ready-built `dist\ComicSorter.exe` sits next to this file - double-click it, no Python needed.
Or run the script:

```bat
python comic_sorter.py
```

Needs Python 3.9+ with tkinter (included in the normal Windows installer). Nothing to pip install.

## Use it

1. **Source folder** – the folder with your loose comics (`.cbz .cbr .cb7 .cbt .pdf .zip .rar .7z .epub .mobi .azw3`).
   Text files and OS litter are **never sorted**: `.txt`, `.nfo`, `.log`, `.ini`, `.db`, `.url`, `.lnk`,
   `thumbs.db`, `desktop.ini`, `.DS_Store`.
2. **Destination folder** – where the sorted library is built. It defaults to a `<source>_sorted`
   folder next to the source, and it can be the source folder itself.
3. **Copy** (default, originals kept) or **Move**.
4. **Include subfolders** if your comics are already in subfolders.
5. **Preview** – every file appears with the series/volume/issue/subtitle it was read from and the
   folder it will land in. Rows in amber are guesses (no issue number), red means little was
   recognised. **Double-click any row** to correct the series, volume, issue or subtitle.
   The **Ed.** column is the edition, **Arc** is the second arc name, **Date** the bracketed date.
6. **Sort comics** – does the work with a progress bar. A `comic_sorter_report_<date>.csv` is
   written into the destination with what was read and where each file went.
7. **Save report CSV** saves the *preview* before you sort anything.

If a target file already exists you can choose to **rename** (`Name (2).cbz`), **skip**, or
**overwrite**. Windows-illegal characters (`: ? * " < > |`) are replaced with `-`, and reserved
names like `CON` are prefixed with `_`.

## Filename shapes it understands

| Filename | Series | Vol. | # | Subtitle |
|---|---|---|---|---|
| `Batman Vol. 2 #003 - Death of the Family (2012).cbz` | Batman | 02 | 003 | Death of the Family |
| `Spawn_Vol_1_Issue_300_(2019)_[Digital]_[dts].cbz` | Spawn | 01 | 300 | – |
| `Saga_Vol_3_#015_-_Arc_Two.cbz` | Saga | 03 | 015 | Arc Two |
| `X-Men - Dark Phoenix Saga.cbz` | X-Men | 01 | – | Dark Phoenix Saga |
| `Saga 12 - Chapter Two.cbz` | Saga | 01 | 012 | Chapter Two |
| `Wolverine - Old Man Logan - Part 2.cbz` | Wolverine | 01 | – | Old Man Logan / Part 2 |
| `X-Men - Dark Phoenix Saga - The Dark Angel Saga 001.cbz` | X-Men | 01 | 001 | Dark Phoenix Saga / The Dark Angel Saga |
| `The_Amazing_Spider-Man_#700.cbz` | The Amazing Spider-Man | 01 | 700 | – |
| `The Boys Vol. 1 #01 - The Name of the Game.cbr` | The Boys | 01 | 001 | The Name of the Game |
| `Saga 012 (2013) (Digital) (Zone-Empire).cbr` | Saga | 01 | 012 | – |
| `Saga v02 #015.cbz` | Saga | 02 | 015 | – |
| `2000AD prog 1234.cbz` | 2000AD | 01 | 1234 | – |
| `2000ad Prog 2000 - Judge Dredd.cbz` | 2000AD | 01 | – | Judge Dredd |
| `X-Men - Dark Phoenix Saga v03 001.cbz` | X-Men | 03 | 001 | Dark Phoenix Saga |
| `Batman Vol. 1 #01 - Court of Owls (2) of 6.cbz` | Batman | 01 | 001 | Court of Owls |
| `Batman Vol. 1 #01 - (2) covers.cbz` | Batman | 01 | 001 | – |
| `Batman - The City of Owls [AI-4320p].cbz` | Batman | 01 | – | The City of Owls |
| `Invincible v01 (2003) - Family Matters.cbz` | Invincible | 01 | – | Family Matters |
| `Daredevil (2019) Vol. 4 - Know Fear.cbz` | Daredevil | 04 | – | Know Fear |
| `Batman – The Killing Joke.cbz` | Batman | 01 | – | The Killing Joke |
| `DC Batman Vol. 2 #003 - Death of the Family (2012).cbz` | DC Batman | 02 | 003 | Death of the Family (2012) |
| `Marvel The Amazing Spider-Man #700.cbz` | Marvel The Amazing Spider-Man | 01 | 700 | – |
| `X-Men - Dark Phoenix Saga 001.cbz` | X-Men | 01 | 001 | Dark Phoenix Saga |
| `Batman 003 - The City of Owls.cbz` | Batman | – | 003 | The City of Owls |
| `001 Batman #005.cbz` | Batman | – | 005 | – |
| `042 The Walking Dead 100.cbz` | The Walking Dead | – | 100 | – |
| `Saga Vol. 1 007 - Arc Two.cbz` | Saga | 01 | 007 | Arc Two |
| `Saga 12 - Chapter Two 004 [2026-02].cbz` | Saga | 01 | 012 | Chapter Two, Ed. 004 (2026-02) |

**Things that are never a subtitle.** `(2) covers`, `3 covers`, `(2) of 6`, `3 of 6`, a lone `(2)`
and release tags like `AI-4320p`, `x265-1080p` are dropped: a name made only of them ends up with
no subtitle at all, and when they trail a real subtitle they are trimmed off
(`Batman Vol. 1 #01 - Court of Owls (2) of 6` -> subtitle "Court of Owls").

**2000AD.** `2000AD`, `2000 AD` and `2000ad` all become the single series **2000AD**, and the word
`prog` is never part of a series name, and its number is the issue:
`2000AD prog 1234` -> `2000AD/2000AD #1234.cbz`.

**The volume.** `Vol. 2`, `Volume 2`, `v2`, `v02`, `v.2` and `vol_1` all set the volume, wherever
they sit in the name: `Saga v02 #015` -> `Vol. 02`, `X-Men - Dark Phoenix Saga v03 001` -> `Vol. 03`.
No volume in the name means no volume at all (no folder, no "Vol." in the title) - it is never
guessed as "Vol. 01".

**Leading three-digit counter.** A three-digit number in front of the title is a file counter and is
dropped from the title: `001 Batman #005.cbz` -> series "Batman" (the number is only used as the
issue if nothing else in the name gives one). `2001 A Space Odyssey` is left alone, since its number
is part of the title.

**Three-digit issue number.** Any three-digit number in the filename is the issue number, wherever
it sits: `X-Men - Dark Phoenix Saga 001` -> arc "Dark Phoenix Saga", **#001**; `Batman 003 - The
City of Owls` -> **#003**, arc "The City of Owls"; `Saga Vol. 1 007 - Arc Two` -> **#007**.
If the name also has a `#`, `Issue` or bare number (`#07`, `Saga 12`), the three-digit number still
wins as the `#` and the other number is kept as the edition (`Ed. 007`), so nothing is lost.
Four-digit numbers are treated as years, not issues.

**Dates in brackets.** A date inside `[ ]` or `( )` is kept in the comic's title (and in the
report's Date column) instead of being thrown away: `(2012)`, `[2026]`, `(2026-01)`, `(01-2026)`,
`[January 2026]` -> `(2026-01)`, `(2026-01-15)` -> `(2026-01)`. Release noise in brackets
(`[Digital]`, `[dts]`, `[Zone-Empire]`) is still dropped.

**Publisher prefix.** `DC`, `DC Comics`, `Marvel` or `Marvel Comics` in front of the title is kept
as part of the series, so it gets its own top-level folder: `DC Batman`, `Marvel The Amazing
Spider-Man`. A title that merely starts with the word keeps it too (`Marvel Zombies #1`), so
nothing is ever lost.

**The dash rule.** A dash with a space on either side (or a real – or — dash) always separates
parts of the name; a hyphen *inside* a word is never a separator (`X-Men`, `Spider-Man`, `one-shot`
stay whole).

- one dash -> `Series - Subtitle`: `X-Men - Dark Phoenix Saga` = series *X-Men*, subtitle *Dark Phoenix Saga*.
- two dashes -> `Series - Subtitle - Arc`: `X-Men - Dark Phoenix Saga - The Dark Angel Saga 001` =
  series *X-Men*, subtitle *Dark Phoenix Saga*, arc *The Dark Angel Saga*, and the file lands in
  `X-Men/Dark Phoenix Saga/The Dark Angel Saga/` (Vol. 01 too when the name has a volume).
- a third dash joins the arc text: `Wolverine - Old Man Logan - Part 2` = subtitle *Old Man Logan*,
  arc *Part 2* -> `Wolverine/Old Man Logan/Part 2/`.

Release noise in `[brackets]` (`Digital`, `dts`, `Zone-Empire`) is dropped; dates (`(2012)`,
`[2026-01]`, `[January 2026]`) are kept as the comic's date.

## Command line (optional, no window)

```bat
python comic_sorter.py "D:\Comics\Unsorted" "D:\Comics\Library" --dry-run
python comic_sorter.py "D:\Comics\Unsorted" "D:\Comics\Library" --move --recursive
```

`--dry-run` prints the plan and changes nothing; `--move` moves instead of copying;
`--recursive` includes subfolders; `--overwrite` overwrites instead of renaming.

## Build a standalone .exe

```bat
python -m pip install pyinstaller
pyinstaller --onefile --windowed --name ComicSorter comic_sorter.py
```

`dist\ComicSorter.exe` (already built here, ~13 MB, no Python needed) runs on any Windows PC.
It also takes the command-line options above, e.g.
`ComicSorter.exe "D:\Comics\Unsorted" "D:\Comics\Library" --dry-run`.
