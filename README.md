# huddle-course-archiver

Archives an e-learning course from a Huddle-based platform (thehuddle.nl): lesson text, attachments (PDFs etc.) and Vimeo videos.

## How it works

- Fetches the course catalog (modules → lessons) from the platform's REST API, authenticated with your browser session cookie
- Per lesson: saves the text as HTML, downloads attachments from the CDN, and downloads Vimeo videos with yt-dlp (using a referer header for domain-restricted embeds)
- Idempotent: reruns skip files that already exist, so interrupted runs resume
- Anything it can't handle is listed in `problems.txt`

## Requirements

Python 3.8+, [yt-dlp](https://github.com/yt-dlp/yt-dlp) and ffmpeg. The script itself uses only the standard library.

## Usage

1. Log in to the course in your browser. In DevTools → Network, copy the `Cookie` request header from any `/api/v4/` request.
2. Set it as an environment variable:
   - bash: `read -rs HUDDLE_COOKIE && export HUDDLE_COOKIE`
   - PowerShell: `$env:HUDDLE_COOKIE = Read-Host "Paste cookie"`
3. Set `SITE` and `COURSE` at the top of the script.
4. Test on one module: `python3 huddle_archive.py --dry-run --module <module-slug>`
5. Run everything: `python3 huddle_archive.py`

## Known limitations

- Audio lessons (e.g. SoundCloud embeds) are reported, not downloaded. Download them manually with yt-dlp.

Intended for personal archiving of courses you have legitimate access to.
