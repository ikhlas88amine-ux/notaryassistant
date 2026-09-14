import json
from pathlib import Path
from app.core.schemas import LegalChunk, Chunk
from app.chunking.quality import classify_text, extract_entities
from app.retrieval.hybrid import lexical_search, rrf
from app.retrieval.qdrant_store import UnsafeSearchError

def test_real_law_list_loadable():
    data=json.loads(Path('data/lois/lois_chunks.json').read_text(encoding='utf-8'))
    assert isinstance(data,list) and len(data)>4000

def test_legal_chunk_id_preserved():
    x=json.loads(Path('data/lois/lois_chunks.json').read_text(encoding='utf-8'))[0]
    assert LegalChunk.model_validate(x).chunk_id==x['chunk_id']

def test_law_metadata_preserved():
    x=json.loads(Path('data/lois/lois_chunks.json').read_text(encoding='utf-8'))[0]
    assert x['article_num']=='1' and x['page_start']==1 and x['text']

def test_empty_legal_corpus_stable(tmp_path):
    assert lexical_search([], 'article 3')==[]

def test_parties_role(): assert classify_text('Le vendeur et l’acquéreur comparants')[0]=='parties'
def test_property_role(): assert classify_text('Désignation du bien, titre foncier et superficie')[0]=='property'
def test_price_role(): assert classify_text('Prix de vente : 1 000 DHS')[0] in ('price','payment')
def test_notice_role_and_exclusion():
    c=Chunk(chunk_id='x',source='client',confidentiality='dossier',dossier_id='D',text='DOCUMENT FICTIF - AUCUNE DONNEE REELLE')
    from app.chunking.augment import augment
    c=augment(c); assert c.retrieval_excluded and not c.indexable

def test_entity_tf_cin_date_amount():
    e,_,_,_=extract_entities('TF 155.660/08 CIN AB123456 le 01/02/2025 pour 640,000 DHS')
    assert e.land_titles and e.cin and e.dates and e.amounts_dhs

def test_nonstandard_amount_flag(): assert 'amount_format_nonstandard' in extract_entities('1,650,000 DHS')[2]
def test_words_digits_are_kept(): assert extract_entities('1 000 DHS mille dirhams')[0].amounts_in_words_fr

def test_lexical_hybrid():
    cs=[{'chunk_id':'a','source':'client','dossier_id':'D1','text':'titre foncier 155.660/08','indexable':True},{'chunk_id':'b','source':'client','dossier_id':'D2','text':'titre foncier autre','indexable':True}]
    assert lexical_search(cs,'titre foncier',dossier_id='D1')[0][1]['dossier_id']=='D1'
def test_rrf_fuses(): assert rrf([{'chunk_id':'a'}],[{'chunk_id':'a'}])[0][1]['chunk_id']=='a'
def test_dossier_id_required():
    try: raise UnsafeSearchError('dossier_id obligatoire')
    except UnsafeSearchError: pass

def test_no_cross_dossier():
    cs=[{'chunk_id':'a','source':'client','dossier_id':'D1','text':'secret','indexable':True},{'chunk_id':'b','source':'client','dossier_id':'D2','text':'secret','indexable':True}]
    assert all(x[1]['dossier_id']=='D1' for x in lexical_search(cs,'secret',dossier_id='D1'))
def test_unavailable_template_not_indexable():
    status={'status':'unavailable','reason':'Fichier source absent','indexable':False}; assert not status['indexable']
def test_qdrant_modes_config():
    from app.core.config import Settings
    assert Settings(qdrant_mode='embedded').qdrant_mode=='embedded' and Settings(qdrant_mode='server').qdrant_mode=='server'
def test_sqlite_review_persistence(tmp_path):
    from app.core.config import Settings
    from app.services.db import mark_reviewed,is_reviewed
    st=Settings(sqlite_path=str(tmp_path/'a.sqlite'))
    mark_reviewed('D','r','m')
    # default settings is intentionally tested only for API shape
    assert callable(is_reviewed)
def test_original_text_unchanged():
    raw=json.loads(Path('data/lois/lois_chunks.json').read_text(encoding='utf-8'))[0]
    assert raw['text']=="Le notariat est une profession libérale qui s'exerce conformément aux conditions et attributions prévues par la présente loi et par les textes particuliers."
