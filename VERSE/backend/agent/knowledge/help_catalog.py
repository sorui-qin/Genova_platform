import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_catalog():
    return json.loads(Path(__file__).with_name('help_catalog.json').read_text(encoding='utf-8'))


def help_catalog():
    from genova_runtime.generation_settings import DEFAULTS
    from genova_runtime.epso_objectives import DEFAULT_OPTIMIZER, DEFAULT_OBJECTIVES, FIXED_PARAMETERS
    from tarpass.filters import METRICS

    catalog = deepcopy(load_catalog())
    defaults = {**DEFAULTS, 'epso': {**DEFAULT_OPTIMIZER, **FIXED_PARAMETERS, 'objectives': DEFAULT_OBJECTIVES}}
    for entry in catalog['entries']:
        if entry.get('default_key'):
            entry['default'] = defaults[entry['model']][entry['default_key']]
    catalog['metric_count'] = len(METRICS)
    return catalog


def knowledge_documents():
    catalog = help_catalog()
    for entry in catalog['entries']:
        for language, content in entry['translations'].items():
            lines = [f"{content['title']} ({entry['id'].replace('-', '_')})", content['summary']]
            if entry['keys']:
                lines.append('Fields: ' + ', '.join(entry['keys']))
            for key in ('details', 'range', 'guidance'):
                if content[key]:
                    lines.append(content[key])
            for section in content.get('sections', []):
                lines.append(section['title'] + ':')
                lines.extend(f"{index + 1}. {item}" if section['ordered'] else '- ' + item
                             for index, item in enumerate(section['items']))
            if 'default' in entry:
                lines.append('Current platform default: ' + json.dumps(entry['default'], ensure_ascii=False))
            lines.append('Platform implementation: ' + entry['source'])
            lines.append(f"Help: /help?article={entry['id']}&lang={language}")
            for ref in entry['references']:
                reference = catalog['references'][ref]
                lines.append(f"[{ref}] {reference['title']}. {reference['citation']} {reference['url']}")
            # A complete entry includes its interpretation and citations in the same retrieval chunk.
            yield entry, language, '# ' + content['title'] + '\n\n' + '\n'.join(lines)


@lru_cache(maxsize=1)
def current_help_hashes():
    from backend.agent.knowledge.utils import compute_content_hash

    hashes = {f"help-{entry['id']}-{language}": compute_content_hash(content)
              for entry, language, content in knowledge_documents()}
    hashes['bundled-tarpass-interpretation-2026-09'] = compute_content_hash(
        Path(__file__).with_name('protocols').joinpath('tarpass_interpretation_2026_09.md').read_text(encoding='utf-8'))
    hashes['tarpass_interpretation_2026_09'] = hashes['bundled-tarpass-interpretation-2026-09']
    return hashes


def is_current_help_revision(source_id, content_hash):
    # Historical Help citations remain resolvable, but search uses the content shipped with this backend.
    return (not source_id.startswith('help-') and source_id not in {'bundled-tarpass-interpretation-2026-09', 'tarpass_interpretation_2026_09'}
            or current_help_hashes().get(source_id) == content_hash)
