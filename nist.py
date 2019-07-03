import subprocess
import threading
import requests
import tarfile
import urllib
import queue
import magic
import os
import re

from flask import Flask, Response, request, redirect, stream_with_context
from flask_caching import Cache
import guide

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
# cache = Cache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': '/tmp'})
cache = Cache(app, config={'CACHE_TYPE': 'redis'})

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

def load_whitelists():
    global library_whitelist
    global whitelist

    with open('whitelist.txt', 'r') as f:
        whitelist = set([l.strip('\n') for l in f])

    if library_whitelist is None:
        lib = os.listdir('./pdfs')
        lib = [b for b in lib if b.endswith(library_extensions)]
        lib = [b for b in lib if os.path.isfile('./pdfs/{}'.format(b))]
        library_whitelist = set(lib)


@cache.memoize(3600)
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
                raise FileNotFoundError
            _next = stamps[stamps.index(_from) + 1]
            return pull_wayback(path, _from=_next)

        whitelist.add(path)
        with open('whitelist.txt', 'a') as f:
            f.write(path + '\n')

        return out
    except FileNotFoundError:
        rq = requests.get('https://{}/{}'.format(_old_url, path))
        if not magic.from_buffer(rq.content).startswith('PDF document'):
            return None

        filepath = 'websites/{}/{}'.format(_old_url, path)
        dirspath = '/'.join(filepath.split('/')[:-1])
        try:
            os.makedirs(dirspath)
        except FileExistsError:
            pass

        with open(filepath, 'wb') as f:
            f.write(rq.content)

        whitelist.add(path)
        with open('whitelist.txt', 'a') as f:
            f.write(path + '\n')

        return rq.content
    except subprocess.CalledProcessError as e:
        return None


def unlink_file(path):
    global whitelist
    if whitelist is None:
        load_whitelists()

    if path not in whitelist:
        return None

    path = 'websites/{}/{}'.format(_old_url, path)
    if os.path.isfile(path):
        os.unlink(path)

    try:
        whitelist.remove(path)
    except KeyError:
        pass


@cache.memoize(600)
def from_filesystem(path):
    global whitelist
    if whitelist is None:
        load_whitelists()

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

        if path.endswith(library_extensions):
            cache.delete_memoized(from_filesystem, path)

        with open(path, 'rb') as f:
            return f.read()

    except FileNotFoundError:
        return None

def format_ref(ref, section, subsection):
    prefix = ' * ' if subsection is None else ' · * '

    uid = ref['uid']
    uid = uid.replace('NIST ', '')
    uid = uid.replace(' Rev ', 'r')

    sid = 'doc-' + ref['uid'].lower().replace(' ', '-')
    exp = ''
    if len(ref['related']) > 0:
        exp = '+<a id="exp-{}"'.format(sid)
        exp += ' onclick="move(\'{}\')'.format(sid)
        exp += '">{}</a>'.format(len(ref['related']))

    tag = '[<a href="https://{}/{}">{}</a>]{} '.format(
            _base_url, ref['url'], uid, exp)
    tag += '– {}'.format(ref['title'])

    tag = prefix + tag
    tag = '<span id="{}" style="display: inline;">{}<br></span>\n'.format(
            sid, tag)

    if len(ref['related']) > 0:
        tag += '<div id="etc-{}" style="display: none">'.format(sid)
        tag += '<p>'
        for link in ref['related']:
            tag += ' · * <a href="https://{}/{}">{}</a><br>'.format(
                    _base_url, link, link.split('/')[-1])
        tag += '</p></div>'

    return tag

@cache.cached(timeout=86400)
def generate_guide(new_page):
    global library_whitelist
    global whitelist

    if whitelist is None or library_whitelist is None:
        load_whitelists()

    sections, refs = guide.load()
    refs = guide.populate(refs, whitelist, extensions=library_extensions)
    refs = guide.populate(refs, library_whitelist, url_prefix='library/',
                    extensions=library_extensions)

    payload = ''
    for name, section in sections.items():
        sid = re.sub('[^a-z-]', '', name.lower().replace(' ', '-'))

        payload += '<section id="{}"><h2 id="doc-{}">'.format(sid, sid)
        payload += '<a href="#doc-{}">+</a> '.format(sid)
        payload += '<span id="title-{}">{}<br><br></span></h2>\n'.format(
            sid, name)

        for uid in sorted(list(section['refs'])):
            ref = refs[uid]
            if ref['url'] is None:
                continue

            payload += format_ref(refs[uid], section, None)

        for idx, (name, subsection) in enumerate(
                section.get('subsections', {}).items()):
            br = '<br>' if idx > 0 else ''

            sid = re.sub('[^a-z-]', '', name.lower().replace(' ', '-'))
            payload += '<span id="doc-{}" style="display: inline">'.format(sid)
            payload += '{}<a href="#doc-{}">::</a> '.format(br, sid)
            payload += '{}<br><br></span>\n'.format(name)

            for uid in sorted(list(subsection['refs'])):
                ref = refs[uid]
                if ref['url'] is None:
                    continue

                payload += format_ref(refs[uid], section, None)

        payload += '<br></section>'

    new_page = new_page.replace('__guide_content__', payload)
    return new_page

def generate_list(new_page, entries, use_path=False):
    count = 0
    payload = ''
    divopen = False
    for entry in entries:
        if not entry.endswith(library_extensions):
            continue

        url = 'https://{}/library/{}'.format(_base_url, entry)
        if use_path:
            url = 'https://{}/{}'.format(_base_url, entry)

        if '/' in entry:
            entry = entry.split('/')[-1]

        count += 1
        if divopen is False:
            divopen = True
            payload += '<p>'

        payload += ('<span style="display: inline">' +
                    '* <a href="{}">{}</a><br></span>\n'.format(url, entry))

        if divopen is True and count % 30 == 0:
            divopen = False
            payload += '</p>'

    if divopen is True:
            payload += '</p>'

    new_page = new_page.replace('<br>\n  -- [End of List] --',
                                payload + '<br>\n  -- [End of List] --')

    return new_page, count

@app.route('/library')
@cache.cached(timeout=600)
def library():
    global library_whitelist
    global library_template
    global whitelist

    if whitelist is None or library_whitelist is None:
        load_whitelists()

    if library_template is None:
        with open('./library.html', 'r') as f:
            library_template = f.read()
        library_template = library_template.replace('__base_url__', _base_url)

    new_page, count = generate_list(library_template, library_whitelist)
    if whitelist is not None:
        new_page, new_count = generate_list(new_page, whitelist, use_path=True)
        count += new_count

    new_page = new_page.replace(
        '<br>\n  -- [End of List] --',
        '<br>\n -- <blink id="count">{}</blink> '.format(count) +
        'files displayed --')

    new_page = generate_guide(new_page)
    return new_page


def worker_tarball(bufline):
    class streamer:
        def tell(self):
            return 0

        def read(self, size):
            return b''

        def seek(self, pos):
            pass

        def write(self, line):
            bufline.put(line)

    tar = tarfile.open(fileobj=streamer(), mode='w:')
    for filename in library_whitelist:
        if not filename.endswith(library_extensions):
            continue

        try:
            tar.add(name='./pdfs/{}'.format(filename),
                arcname='./extra/{}'.format(filename),
                recursive=False)
        except FileNotFoundError:
            pass

    for path in whitelist:
        path = 'websites/{}/{}'.format(_old_url, path)
        if not path.endswith(library_extensions):
            continue

        if not os.path.isfile(path):
            path = path.lower()

        try:
            tar.add(name=path, recursive=False)
        except FileNotFoundError:
            pass

    tar.close()


def generate_tarball():
    bufline = queue.Queue(1024)
    worker = threading.Thread(target=worker_tarball, args=(bufline,))
    worker.start()
    while worker.is_alive():
        yield bufline.get(timeout=60)


@app.route('/library/csrc.tar')
def library_tarball():

    if whitelist is None or library_whitelist is None:
        load_whitelists()

    response = Response(
        stream_with_context(generate_tarball()), mimetype='application/x-tar')
    response.headers['Content-Disposition'] = 'attachment; filename=csrc.tar'
    return response


@app.route('/library/<book>')
def library_file(book):
    global library_whitelist

    if library_whitelist is None:
        load_whitelists()

    book = redact_path(book)
    if book.endswith(library_extensions) and book in library_whitelist:
        with open('./pdfs/{}'.format(book), 'rb') as f:
            out = f.read()

        mime = magic.Magic(mime=True)
        mimetype = mime.from_buffer(out[:2**20])
        return Response(out, mimetype=mimetype)

    return 'File not found.', 404


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


def zero_length(path):
    referrer = request.headers.get('Referer') or ''
    if not referrer.startswith('https://{}/'.format(_base_url)):
        referrer = 'https://{}'.format(_base_url)

    text = 'File has been found, but has been corrupted :(<br>\n<br>\n'
    if path.endswith(library_extensions):
        text += ('You can try to force download by clicking here: ' +
                 '<a href="?wayback=forced">here</a>!'.format(path))

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
    global whitelist
    whitelist = None

    path = fixup_path(path)
    path = redact_path(path)

    forced = False
    if path.endswith('?wayback=forced'):
        forced = True
        path = path[:-len('?wayback=forced')]
        cache.delete_memoized(from_filesystem, path)

    out = from_filesystem(path)
    if out is None or (forced and len(out) == 0):
        if forced and out is not None:
            unlink_file(path)

        pull_wayback(path)
        cache.delete_memoized(from_filesystem, path)

        out = from_filesystem(path)

    if out is None:
        return not_found(path), 404

    if len(out) == 0:
        return zero_length(path), 500

    if path.endswith('.js'):
        mimetype = 'text/script'
    elif path.endswith('.css'):
        mimetype = 'text/css'
    else:
        mime = magic.Magic(mime=True)
        mimetype = mime.from_buffer(out[:2**20])

    if 'application' in mimetype or path.endswith(library_extensions):
        return Response(out, mimetype=mimetype)

    out = out.replace(bytes(_old_url, 'utf8'), bytes(_base_url, 'utf8'))
    out = out.replace(b'webmaster-csrc@nist.gov', b'webmaster-csrc@nist.rip')

    # disclaimer
    out = out.replace(b'alt="CSRC Logo" class="csrc-header-logo"></a>',
                b'alt="CSRC Logo" class="csrc-header-logo"></a>' +
                b'<div class="csrc-header-logo" style="font-size:' +
                b'smaller; color: #ffffff; text-align: center; margin-top:' +
                b'1em;">This is an <a href="' +
                bytes('https://{}/library">'.format(_base_url), 'utf8') +
                b'archive</a><br>(replace <a href="' +
                bytes('https://{}">.gov</a>'.format(_old_url), 'utf8') +
                bytes(' by <a href="https://{}">'.format(_base_url), 'utf8') +
                b'.rip</a>)</div>')
    return Response(out, mimetype=mimetype)


if __name__ == '__main__':
    # app.run(host='0.0.0.0', port='8080')
    app.run(host='127.0.0.1', port='8080')
