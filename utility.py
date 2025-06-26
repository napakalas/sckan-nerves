
#===============================================================================

try:
    from mapmaker.utils import log as logger     # type: ignore
except ImportError:
    import structlog
    logger = structlog.get_logger()

log = logger.bind(type='knowledge')

#===============================================================================

from pathlib import Path

SOURCE_DIR = Path('data/source')
GENERATED_DIR = Path('data/generated')

#===============================================================================

from json import JSONDecodeError
import requests

LOOKUP_TIMEOUT = 30    # seconds; for `requests.get()`

#===============================================================================

def request_json(endpoint, **kwds):
    try:
        response = requests.get(endpoint,
                                headers={'Accept': 'application/json'},
                                timeout=LOOKUP_TIMEOUT,
                                **kwds)
        if response.ok:
            try:
                return response.json()
            except JSONDecodeError:
                error = 'Invalid JSON returned'
        else:
            error = response.reason
    except requests.exceptions.RequestException as exception:
        error = f'Exception: {exception}'
    log.warning("Couldn't access endpoint", endpoint=endpoint, error=error)
    return None

#===============================================================================

SCICRUNCH_PRODUCTION = 'sckan-scigraph'
SCICRUNCH_API_ENDPOINT = 'https://scicrunch.org/api/1'
SCICRUNCH_SPARC_API = f'{SCICRUNCH_API_ENDPOINT}/{{SCICRUNCH_RELEASE}}'
SCICRUNCH_INTERLEX_VOCAB = f'{SCICRUNCH_API_ENDPOINT}/ilx/search/curie/{{TERM}}'

SCICRUNCH_SPARC_VOCAB = f'{SCICRUNCH_SPARC_API}/vocabulary/id/{{TERM}}.json'
SCICRUNCH_SPARC_LABEL = f'{SCICRUNCH_API_ENDPOINT}/ilx/search/term/{{LABEL}}'

#===============================================================================

import os
import pandas as pd

params = {
    'api_key': os.environ.get('SCICRUNCH_API_KEY'),
    'limit': 9999,
}

def get_existing_term(term: str):
    if term.startswith('FMA'):
        data = request_json(SCICRUNCH_SPARC_VOCAB.format(SCICRUNCH_RELEASE=SCICRUNCH_PRODUCTION, TERM=term), params=params)
        if (labels:=data.get('labels')):
            return get_term_from_label(labels[0])
    elif term.startswith('ILX') or term.startswith('UBERON'):
        data = request_json(SCICRUNCH_INTERLEX_VOCAB.format(SCICRUNCH_RELEASE=SCICRUNCH_PRODUCTION, TERM=term), params=params)
        existing_ids = [eid['curie'] for eid in data.get('data', {}).get('existing_ids', [])]
        return existing_ids if existing_ids else pd.NA
    return pd.NA

def get_term_from_label(label):
    data = request_json(SCICRUNCH_SPARC_LABEL.format(LABEL=label), params=params)
    existing_ids = [eid['curie'] for eid in data.get('data', {}).get('existing_ids', pd.NA)]
    return existing_ids if existing_ids else pd.NA

#===============================================================================
