import collections
import re

def load(filename='index.txt'):
    refs = collections.OrderedDict()
    section = None
    sections = collections.OrderedDict()
    subsection = None
    with open(filename, 'r') as f:
        for idx, line in enumerate(f):
            line = line.strip('\n').strip(' ')
            if len(line) < 1:
                continue
            elif line.startswith('[section] :-'):
                section = line[13:].strip(' ')
                subsection = None
                sections[section] = sections.get(
                    section,
                    {'subsections': collections.OrderedDict(), 'refs': set()})
            elif line.startswith('[subsection] :-'):
                subsection = line[15:].strip(' ')
                sections[section]['subsections'][subsection] = (
                        sections[section]['subsections'].get(subsection,
                        {'refs': set()}))
            elif '|' not in line:
                raise RuntimeError('Invalid: {} (l.{})'.format(line, idx + 1))
            else:
                uid, title = line.split('|', 1)
                uid, title = uid.strip(' '), title.strip(' ')
                refs[uid] = {
                    'uid': uid, 'title': title, 'url': None, 'related': []}
                if subsection is not None:
                    sections[section]['subsections'][subsection][
                        'refs'].add(uid)
                else:
                    sections[section]['refs'].add(uid)

    return sections, refs

def populate(refs, urls, url_prefix='', extensions=('pdf')):
    if isinstance(urls, str):
        with open(urls, 'r') as f:
            urls = f.read().split('\n')

    for uid, entry in refs.items():
        oid = uid
        uid, title = uid.lower(), entry['title'].lower()
        uid = uid.replace('Rev-', 'Rev')

        bonuses = []
        pattern = None
        candidates = []
        for prefix in ['sp', 'fips']:
            if uid.startswith(prefix):
                bonuses = uid.replace('-', ' ').split(' ')
                best = 'nistpub'

                pattern = ('[. _-]*'.join(
                    ['0?' + ft for ft in
                    uid.split(' ')[1].split('-')]) + '[^0-9]')
                if uid == 'fips 140':
                    pattern = 'fips[ _-]*' + pattern
                pattern = re.compile(pattern)

        for prefix in ['ir', 'sb', 'sp', 'fips']:
            if uid.startswith('nist {}'.format(prefix)):
                bonuses = uid.replace('-', ' ').split(' ')
                bonuses.append('nistir')
                best = 'nist{}'.format(prefix)

                pattern = ('(nist)?' + '[. _-]*'.join([prefix] +
                    uid.split(' ')[2].split('-')) + '[^0-9]')
                pattern = re.compile(pattern)
                break

        if pattern is None:
            month = None
            if 'january' in uid:
                month = '0?1'
            if 'february' in uid:
                month = '0?2'
            if 'march' in uid:
                month = '0?3'
            if 'april' in uid:
                month = '0?4'
            if 'may' in uid:
                month = '0?5'
            if 'june' in uid:
                month = '0?6'
            if 'july' in uid:
                month = '0?7'
            if 'august' in uid:
                month = '0?8'
            if 'september' in uid:
                month = '0?9'
            if 'october' in uid:
                month = '10'
            if 'november' in uid:
                month = '11'
            if 'december' in uid:
                month = '12'

            if month is not None:
                pattern = '[ _-]+'.join([uid[-2:], month]) + '[^0-9]'
                pattern = re.compile(pattern)
                best = 'nistbul'
                if 'ITL Security Bulletin' in title:
                    best = 'itl'

        if pattern is None:
            print(uid)
            continue

        for url in urls:
            if not url.lower().endswith(extensions):
                continue

            if pattern.search(url.lower()):
                candidates.append(url_prefix + url)

        if len(candidates) < 1:
            continue

        scores = []
        for c in candidates:
            c = c.lower()

            score = 0
            score += 10 if not '/' in c else 0
            for r in range(1, 5):
                if 'r{}'.format(r) in c or 'rev{}'.format(r) in c:
                    score += r * 0.01
            if '2nd' in c or 'second' in c:
                score += 0.01
            if '3rd' in c or 'third' in c:
                score += 0.02
            score += 8 if best in c else 0
            score += 4 if 'final' in c else 0
            score += 1 if 'pdf' in c else 0
            score += 0.5 if 'txt' in c else 0
            score += 0.6 if 'update' in c else 0
            score += 0.2 if 'revised' in c else 0
            score += 0.1 if 'pub' in c else 0
            score -= 0.1 if 'note' in c else 0
            score -= 0.2 if 'draft' in c else 0
            score -= 0.2 if 'part' in c else 0
            score -= 0.2 if 'annex' in c else 0
            score -= 0.3 if 'informative' in c else 0
            score -= 0.3 if 'excerpt' in c else 0
            score -= 0.3 if 'errata' in c else 0
            score -= 0.4 if 'presentation' in c else 0
            score -= 0.4 if 'supplemental' in c else 0

            for b in bonuses:
                score += 0.1 if b in c else 0

            for b in title.lower().split(' '):
                score += 0.1 if b in c else 0

            scores.append((score, c))

        scores.sort(key=lambda x: -x[0])
        refs[oid]['url'] = scores[0][1]
        refs[oid]['related'] = (
            (refs[oid]['related'] or []) + [sc[1] for sc in scores[1:]])

    return refs
