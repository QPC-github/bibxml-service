import json
from typing import Union, Tuple, Any

from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db.models.query import QuerySet, Q
from django.db.models import TextField
from django.db.models.functions import Cast

from .exceptions import RefNotFoundError
from .models import RefData


# TODO: Obsolete, now that we gave up on multi-DB approach
RefDataManager = RefData.objects


def list_refs(dataset_id) -> QuerySet[RefData]:
    return RefDataManager.filter(dataset__iexact=dataset_id)


def search_refs_json_repr_match(text: str) -> QuerySet[RefData]:
    """Uses given string to search across serialized JSON representations
    of Relaton citation data.

    Supports typical websearch operators like quotes, plus, minus, OR, AND.
    """
    return (
        RefDataManager.
        annotate(search=SearchVector(Cast('body', TextField()))).
        filter(search=SearchQuery(text, search_type='websearch')))


def search_refs_relaton_struct(
        *objs: Union[dict[Any, Any], list[Any]]) -> QuerySet[RefData]:
    """Uses PostgreSQL’s JSON containment query.

    Returns citations which Relaton structure contains
    at least one of given ``obj`` structures (they are OR'ed).

    .. seealso:: PostgreSQL docs on ``@>`` operator.
    """
    subqueries = ['body @> %s::jsonb' for obj in objs]
    query = 'SELECT * FROM api_ref_data WHERE %s' % ' OR '.join(subqueries)
    return (
        RefDataManager.
        raw(query, [json.dumps(obj) for obj in objs]))


def list_doctypes() -> list[Tuple[str, str]]:
    """Lists all distinct ``docid[*].doctype`` values among citation data.

    Returns a list of 2-tuples (document type, example document ID).
    """
    return [
        (i.doctype, i.sample_id)
        for i in (
            RefDataManager.
            order_by('?').  # This may be inefficient as dataset grows
            raw('''
                select distinct on (doctype) id, doctype, sample_id
                from (
                    select id, jsonb_array_elements_text(
                        jsonb_path_query_array(
                            body,
                            '$.docid[*].type'
                        )
                    ) as doctype, jsonb_array_elements_text(
                        jsonb_path_query_array(
                            body,
                            '$.docid[*].id'
                        )
                    ) as sample_id
                    from api_ref_data
                ) as item
                '''))]


def get_indexed_ref(dataset_id, ref, format='relaton'):
    """Retrieves citation from static indexed dataset.

    :param format string: "bibxml" or "relaton"
    :returns object: if format is "relaton", a dict.
    :returns string: if format is "bibxml", an XML string.
    :raises RefNotFoundError: either reference or requested format not found
    """

    return get_indexed_ref_by_query(dataset_id, Q(ref__iexact=ref), format)


def get_indexed_ref_by_query(dataset_id, query: Q, format='relaton'):
    """Retrieves citation from static indexed dataset.

    :param format string: "bibxml" or "relaton"
    :returns object: if format is "relaton", a dict.
    :returns string: if format is "bibxml", an XML string.
    :raises RefNotFoundError: either reference or requested format not found
    """

    if format not in ['relaton', 'bibxml']:
        raise ValueError("Unknown citation format requested")

    try:
        result = RefDataManager.get(
            query &
            Q(dataset__iexact=dataset_id))
    except RefData.DoesNotExist:
        raise RefNotFoundError(
            "Cannot find matching reference in given dataset",
            repr(Q))
    except RefData.MultipleObjectsReturned():
        raise RefNotFoundError(
            "Multiple references match query in given dataset",
            repr(Q))

    if format == 'relaton':
        return result.body

    else:
        bibxml_repr = result.representations.get('bibxml', None)
        if bibxml_repr:
            return bibxml_repr
        else:
            raise RefNotFoundError(
                "BibXML representation not found for requested reference",
                repr(Q))
