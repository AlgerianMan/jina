import os

from jina import Document
from jina.executors.indexers import BaseIndexer
from jina.flow import Flow
import pytest


@pytest.fixture
def config(tmpdir):
    os.environ['JINA_CRUD_ADVANCED_WORKSPACE'] = str(tmpdir)
    yield
    del os.environ['JINA_CRUD_ADVANCED_WORKSPACE']


def get_docs_to_index(contents):
    for i, content in enumerate(contents):
        document = Document()
        document.id = str(f'{i}' * 16)
        document.text = content
        yield document


def get_docs_to_delete(doc_id_to_chunk_ids):
    for i, (doc_id, chunks) in enumerate(doc_id_to_chunk_ids.items()):
        document = Document()
        document.id = str(f'{i}' * 16)
        for chunk in chunks:
            document.chunks.append(chunk)
        yield document


def validate_index(tmpdir, validation_data):
    assert len(validation_data) > 0
    for index_file, expected_size in validation_data:
        index = BaseIndexer.load(str(os.path.join(tmpdir, index_file)))
        assert index.size == expected_size


def test_crud_advanced_example(tmpdir, config, mocker, monkeypatch):
    '''
    This test indexes documents into an example flow and updates one document.
    The update is implemented as delete & index.
    '''
    monkeypatch.setenv("RESTFUL", 'False')
    monkeypatch.setenv("JINA_CRUD_ADVANCED_WORKSPACE", str(tmpdir))

    # generate documents to index
    index_data = get_docs_to_index([
        '0,1,2,3,4,5,6,7,8,9',
        'a ijk,b ijk,c jk',
        'w mno,x no,y op,z i',
    ])

    response_docs = []

    def on_index_done(resp):
        response_docs.extend(resp.docs)

    # insert documents into the indexers
    # response_docs is used to store the chunks generated by the segmenter via on_index_done
    # at the moment the deletion of chunks via document_id is not possible
    # therefore, the chunks are needed later on when when deleting the documents
    with Flow.load_config('flow-index.yml') as index_flow:
        index_flow.index(
            index_data,
            on_done=on_index_done
        )

    validate_index(
        tmpdir,
        validation_data=[
            ('docIndexer.bin', 3),
            ('chunkidx.bin', 17),
            ('vecidx.bin', 17)
        ]
    )

    # pick document 0 to be deleted
    delete_data = get_docs_to_delete({
        0: response_docs[0].chunks
    })

    # run flow for deletion
    with Flow.load_config('flow-index.yml') as delete_flow:
        delete_flow.delete(delete_data)

    validate_index(
        tmpdir,
        validation_data=[
            ('docIndexer.bin', 2),
            ('chunkidx.bin', 7),
            ('vecidx.bin', 7)
        ]
    )

    # generate a new document 0 as a replacement for the deleted one
    updated_data = get_docs_to_index([
        '1 ijk,2 jk,3 k',
    ])

    # insert the updated document
    index_flow = Flow.load_config('flow-index.yml')
    with index_flow:
        index_flow.index(updated_data)

    validate_index(
        tmpdir,
        validation_data=[
            ('docIndexer.bin', 3),
            ('chunkidx.bin', 10),
            ('vecidx.bin', 10)
        ]
    )
    mock = mocker.Mock()

    def validate_granularity_1(resp):
        mock()
        assert len(resp.docs) == 3
        for doc in resp.docs:
            assert doc.granularity == 0
            assert len(doc.matches) == 3
            assert doc.matches[0].granularity == 0

        assert resp.docs[0].text == '2 jk'
        assert (
                resp.docs[0].matches[0].text
                == '1 ijk,2 jk,3 k'
        )

        assert resp.docs[1].text == 'i'
        assert (
                resp.docs[1].matches[0].text
                == 'w mno,x no,y op,z i'
        )

        assert resp.docs[2].text == 'm'
        assert (
                resp.docs[2].matches[0].text
                == 'w mno,x no,y op,z i'
        )

    search_data = [
        '2 jk',
        'i',
        'm',
    ]

    with Flow.load_config('flow-query.yml') as search_flow:
        search_flow.search(
            input_fn=search_data,
            on_done=validate_granularity_1,
            callback_on='body',
        )

    mock.assert_called_once()
