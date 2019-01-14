import subprocess
import urllib
import magic
import os
import re

from flask import Flask, Response, request, redirect

_bin = 'wayback_machine_downloader' # gem install
_old_url = 'csrc.nist.gov'
_base_url = 'csrc.nist.rip'

whitelist = None
blacklist = ('axd', )
library_template = None
library_whitelist = None
library_extensions = (
    '.pdf',
    '.doc',
    '.docx',
    '.epub',
    '.ps',
    '.rtf',
    '.txt',
    '.wpd',
    '.xls',
    '.xlsx',
    '.xml',
    '.zip', )

before = '20181224085649'
stamps = [
    '20181220085649',
    '20180620085649',
    '20170620085649',
    '20100620085649',
    '20000620085649', ]

app = Flask(__name__)


def fixup_path(path):
    if '/' in request.url:
        last = request.url.split('/')[-1]

        if '/' in path:
            parts = path.split('/')
            if last != parts[-1]:
                path = '/'.join(parts[:-1] + [last])
    return path


def redact_path(path):
    path = path[:256]

    path = re.sub('[\\*%"\']', '', path)
    path = re.sub('\.\.+', '.', path)
    return re.sub('//+', '/', path)


def pull_wayback(path, _from=stamps[0], _to=before):
    url = 'https://{}/{}'.format(_old_url, urllib.parse.quote(path))
    url = url.replace('%3Fext%3D', '?ext=')
    if url.endswith('index.html'):
        url = url[:-10]

    if url.endswith(blacklist):
        return None

    try:
        try:
            out = subprocess.check_output(
                [_bin, url, '--exact-url', '--to', _to, '--from', _from],
                stderr=subprocess.STDOUT, shell=False, timeout=30)
        except subprocess.TimeoutExpired:
            out = b'found 0 snaphots No files'

        # magic strings in error message to check for wayback failure
        if b'found 0 snaphots' in out and b'No files' in out:
            if _from not in stamps or _from == stamps[-1]:
                return None
            _next = stamps[stamps.index(_from) + 1]
            return pull_wayback(path, _from=_next)

        whitelist.append(path)
        with open('whitelist.txt', 'a') as f:
            f.write(path + '\n')

        return out

    except subprocess.CalledProcessError as e:
        return None


def from_filesystem(path, use_whitelist=True):
    global whitelist

    if use_whitelist:
        if whitelist is None:
            with open('whitelist.txt', 'r') as f:
                whitelist = [l.strip('\n') for l in f]
        if path not in whitelist:
            return None

    path = 'websites/{}/{}'.format(_old_url, path)
    try:
        if os.path.isdir(path) or os.path.isdir(path.lower()):
            if not path.endswith('/'):
                path += '/'
            path += 'index.html'

        if not os.path.isfile(path):
            path = path.lower()

        with open(path, 'rb') as f:
            return f.read()

    except FileNotFoundError:
        return None

def generate_list(new_page, entries):
    count = 0
    divopen = False
    for entry in entries:
        if not entry.endswith(library_extensions):
            continue

        if '/' in entry:
            entry = entry.split('/')[-1]

        count += 1
        if divopen is False:
            divopen = True
            new_page = new_page.replace(
                '<br>\n  -- [End of List] --',
                    '<p>' + '<br>\n  -- [End of List] --')

        url = 'https://{}/library/{}'.format(_base_url, entry)
        new_page = new_page.replace(
            '<br>\n  -- [End of List] --', '<span style="display: inline">' +
            '* <a href="{}">{}</a><br></span>\n'.format(
                url, entry) + '<br>\n  -- [End of List] --')

        if divopen is True and count % 30 == 0:
            divopen = False
            new_page = new_page.replace(
                '<br>\n  -- [End of List] --',
                    '</p>' + '<br>\n  -- [End of List] --')

    if divopen is True:
        new_page = new_page.replace(
                '<br>\n  -- [End of List] --',
                    '</p>' + '<br>\n  -- [End of List] --')

    return new_page, count

@app.route('/library', defaults={'book': None})
@app.route('/library/<book>')
def library(book):
    global library_whitelist
    global library_template

    if library_whitelist is None:
        lib = os.listdir('./pdfs')
        lib = [b for b in lib if b.endswith(library_extensions)]
        lib = [b for b in lib if os.path.isfile('./pdfs/{}'.format(b))]
        library_whitelist = list(lib)

    if book is not None:
        book = redact_path(book)

        if book.endswith(library_extensions) and book in library_whitelist:
            with open('./pdfs/{}'.format(book), 'rb') as f:
                out = f.read()

            mime = magic.Magic(mime=True)
            mimetype = mime.from_buffer(out)
            return Response(out, mimetype=mimetype)

        return 'File not found.', 404

    if library_template is None:
        with open('./library.html', 'r') as f:
            library_template = f.read()
        library_template = library_template.replace('__base_url__', _base_url)

    new_page, count = generate_list(library_template, library_whitelist)
    if whitelist is not None:
        new_page, new_count = generate_list(new_page, whitelist)
        count += new_count

    new_page = new_page.replace(
        '<br>\n  -- [End of List] --',
        '<br>\n -- <blink id="count">{}</blink> '.format(count) +
        'files displayed --')

    return new_page


def not_found(path):
    referrer = request.headers.get('Referer') or ''
    if not referrer.startswith('https://{}/'.format(_base_url)):
        referrer = 'https://{}'.format(_base_url)

    text = 'Unable to pull file from archive.org :('
    if path.endswith(library_extensions):
        text = ('Unable to pull this media from the archive,' +
                ' send us your copy ' +
                '<a href="mailto:webmaster-csrc@nist.rip">here</a>!')

    text = ('<html><body style="font-family: mono; color: #555;' +
            'background-color: #fafafa;">' + text)
    text += '<br>\n<br>\n'
    text += 'Go <a href="{}">back</a> or '.format(referrer)
    text += 'browse the '
    text += '<a href="https://{}/library">library</a>.'.format(_base_url)
    text += '<br>\n<br>\n<br>\n–––––––––––<br>\n<br>\n'
    text += 'Contact us <a href="mailto:webmaster-csrc@nist.rip">here</a>'
    text += ' to report issues.'

    text += '</body></html>'
    return text


@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def nist(path):
    path = fixup_path(path)
    path = redact_path(path)

    out = from_filesystem(path)
    if out is None:
        pull_wayback(path)
        out = from_filesystem(path)

    if out is None:
        return not_found(path), 404

    if path.endswith('.js'):
        mimetype = 'text/script'
    elif path.endswith('.css'):
        mimetype = 'text/css'
    else:
        mime = magic.Magic(mime=True)
        mimetype = mime.from_buffer(out)

    out = out.replace(bytes(_old_url, 'utf8'), bytes(_base_url, 'utf8'))
    out = out.replace(b'webmaster-csrc@nist.gov', b'webmaster-csrc@nist.rip')
    return Response(out, mimetype=mimetype)


if __name__ == '__main__':
    # app.run(host='0.0.0.0', port='8080')
    app.run(host='127.0.0.1', port='8080')
