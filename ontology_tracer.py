### This code is used to extract information relating to ontology terms in FMA and UBERON.

# The relation regarding subClassOf, part_of, and branch_of is quite different, hence need a different handling.

import rdflib
from utility import SOURCE_DIR, GENERATED_DIR, to_curie, clean_literal, ONTOLOGIES
from collections import defaultdict
from tqdm import tqdm
import json
import pathlib

class OntologyTracer:
    """
    The main extracted data is __onto_data, loading from a json file consisting of:
        - 'id_to_labels'
        - 'label_to_ids'
        - 'subclass_of'
        - 'branch_of'
        - 'part_of'
        - 'subclass_part_of'
        - 'nerves'
        - 'superclass_of'
        - 'has_branches'
        - 'has_parts'
        - 'superclass_of_has_parts'
    There is also `load_source` function to load the data from uberon.owl and fma.owl
    """

    def __init__(self, ontodata_file = None):
        if (ontodata_file:=pathlib.Path(ontodata_file)).exists():
            with open(ontodata_file, 'r') as f:
                self.__onto_data = json.load(f)
                self.__onto_data['superclass_of']= self.__inverse_relation(self.__onto_data['subclass_of'])
                self.__onto_data['has_branches']= self.__inverse_relation(self.__onto_data['branch_of'])
                self.__onto_data['has_parts']= self.__inverse_relation(self.__onto_data['part_of'])
                self.__onto_data['superclass_of_has_parts']= self.__inverse_relation(self.__onto_data['subclass_part_of'])
        else:
            self.__onto_data = {}

    def load_source(self):
        # load fma.owl
        g_fma = rdflib.Graph()
        g_fma.parse(SOURCE_DIR /'fma.owl', format='xml')
        # and uberon.owl
        g_uberon = rdflib.Graph()
        g_uberon.parse(SOURCE_DIR /'uberon.owl', format='xml')

        # get all labels
        label_to_ids = defaultdict(list)
        id_to_labels = defaultdict(list)
        for g in [g_uberon, g_fma]:
            for s, p, o in g:
                if ('rdf-schema#label' in p or 'fma/synonym' in p or 'hasExactSynonym' in p) and (ONTOLOGIES['UBERON'] in s or ONTOLOGIES['FMA'] in s):
                    label_to_ids[clean_literal(o).lower()] += [to_curie(s)]
                    id_to_labels[to_curie(s)] += [clean_literal(o)]

        # Get all subclasses
        q = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX obo: <http://purl.obolibrary.org/obo/>
        SELECT ?subclass ?superclass WHERE {
        {
            ?subclass rdfs:subClassOf ?superclass .
            FILTER (?subclass != ?superclass)
        }
        }
        """
        # collect subclass_of from both graphs
        subclass_of = defaultdict(set)
        self.__collect_relations([g_uberon, g_fma], q, subclass_of, id_to_labels)
        # invers subclass_of become superclass_od
        superclass_of = self.__inverse_relation(subclass_of)

        # get all branches
        branch_of = defaultdict(set)
        # UBERON branch
        q = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX obo: <http://purl.obolibrary.org/obo/>
        SELECT ?subclass ?superclass WHERE {
        {
            ?subclass rdfs:subClassOf ?restriction .

            ?restriction owl:onProperty obo:RO_0002380 ;
                        owl:someValuesFrom ?superclass .
        }
        FILTER (?subclass != ?superclass)
        }
        """
        # collect branch_of from UBERON
        self.__collect_relations([g_uberon], q, branch_of, id_to_labels)
        # FMA branch
        q = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX obo: <http://purl.obolibrary.org/obo/>

        SELECT ?subclass ?superclass WHERE {
        {
            ?subclass rdfs:subClassOf ?restriction .

            ?restriction owl:onProperty <http://purl.org/sig/ont/fma/branch_of> ;
                        owl:someValuesFrom ?superclass .
        }
        FILTER (?subclass != ?superclass)
        }
        """
        # collect branch_of from UBERON
        self.__collect_relations([g_fma], q, branch_of, id_to_labels)

        # get all parts
        part_of = defaultdict(set)
        # UBERON parts
        q = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX obo: <http://purl.obolibrary.org/obo/>

        SELECT ?subclass ?superclass WHERE {
        {
            ?subclass rdfs:subClassOf ?restriction .

            ?restriction owl:onProperty obo:BFO_0000050 ;
                        owl:someValuesFrom ?superclass .
        }
        FILTER (?subclass != ?superclass)
        }
        """
        # collect part_of from UBERON
        self.__collect_relations([g_uberon], q, part_of, id_to_labels)
        # FMA parts
        q = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX obo: <http://purl.obolibrary.org/obo/>
        SELECT ?subclass ?superclass WHERE {
        ?subclass rdfs:subClassOf ?restriction .
        {
            ?restriction owl:onProperty ?prop ;
                        owl:someValuesFrom ?superclass .
        }
        FILTER (?prop IN (
            <http://purl.org/sig/ont/fma/constitutional_part_of>,
            <http://purl.org/sig/ont/fma/member_of>,
            <http://purl.org/sig/ont/fma/regional_part_of>,
            <http://purl.org/sig/ont/fma/part_of>
        ))
        FILTER (?subclass != ?superclass)
        }
        """
        # collect part_of from UBERON
        self.__collect_relations([g_fma], q, part_of, id_to_labels)

        # the combination of subclass_of and part_of
        # the combination excludes part_of that also branch_of
        subclass_part_of = {
            term_id: set(supers) for term_id, supers in subclass_of.items()
        }
        for term_id, parts in part_of.items():
            subclass_part_of.setdefault(term_id, set()).update(
                parts - branch_of.get(term_id, set())
            )

        # Get all nerves
        # Nerves are the subclasses of 'UBERON:0001021', 'FMA:65132', 'FMA:61284', 'FMA:65239'
        nerves = set()
        for nerve_id in ['UBERON:0001021', 'FMA:65132', 'FMA:61284', 'FMA:65239']:
            nerves.update(self.trace_relation(nerve_id, superclass_of, 0, []).keys())
        self.__onto_data = {
            'id_to_labels': dict(id_to_labels),
            'label_to_ids': dict(label_to_ids),
            'subclass_of': {k:list(v) for k,v in subclass_of.items()},
            'branch_of': {k:list(v) for k,v in branch_of.items()},
            'part_of': {k:list(v) for k,v in part_of.items()},
            'subclass_part_of': {k:list(v) for k,v in subclass_part_of.items()},
            'nerves': list(nerves)
        }

        # dump data to JSON
        with open(GENERATED_DIR / 'UBERON_FMA_STRUCTURE.json', 'w') as f:
            json.dump(self.__onto_data, f)

        # complete the inverse data
        self.__onto_data['superclass_of']= self.__inverse_relation(self.__onto_data['subclass_of'])
        self.__onto_data['has_branches']= self.__inverse_relation(self.__onto_data['branch_of'])
        self.__onto_data['has_parts']= self.__inverse_relation(self.__onto_data['part_of'])
        self.__onto_data['superclass_of_has_parts']= self.__inverse_relation(self.__onto_data['subclass_part_of'])

        print('Finish loading data')

    # Functions to manage A to list of B relation

    def onto_data(self):
        return self.__onto_data

    def __collect_relations(self, graphs, query, target_dict, id_to_labels):
        """
        Collect subclass/superclass relations from graphs into target_dict.

        graphs: list of rdflib graphs to query
        query: SPARQL query string
        target_dict: defaultdict(set) where results are stored
        id_to_labels: dict of valid IDs
        """
        for g in graphs:
            for row in g.query(query):
                subclass = to_curie(row.subclass)
                superclass = to_curie(row.superclass)
                if subclass in id_to_labels and superclass in id_to_labels:
                    target_dict[subclass].add(superclass)

    def trace_relation(self, term_id: str, source: dict, distance: int=0, loopcheck=None) -> dict:
        """
        Generic recursive tracer for hierarchical relations.
        - term_id: starting node
        - distance: current distance from the root
        - loopcheck: list of visited nodes to avoid cycles
        - source: dictionary mapping term_id -> list of related ids (parents or children)
        """
        if loopcheck is None:
            loopcheck = []
        distance += 1
        relations = {}
        for rel_id in source.get(term_id, []):
            if rel_id not in loopcheck:
                relations[rel_id] = {"distance": distance}
                loopcheck.append(rel_id)
        if relations:
            for rel_id in list(relations.keys()):
                relations.update(self.trace_relation(rel_id, source, distance, loopcheck))
        return relations

    def __inverse_relation(self, relation_dict):
        """
        Build an inverse relation.

        relation_dict: dict mapping term_id -> set of super-relations
        """
        inverse = defaultdict(set)
        for term_id, supers in relation_dict.items():
            for super_term in supers:
                inverse[super_term].add(term_id)

        return inverse

    def expand_relation(self, relation_dict, desc=""):
        """
        Build a ful relation and expand it with trace_relation.

        relation_dict: dict mapping term_id -> set of super-relations
        desc: optional description for tqdm progress bar
        """
        expanded = defaultdict(set)
        for term_id in tqdm(list(relation_dict.keys()), desc=desc):
            expanded[term_id] = self.trace_relation(term_id, relation_dict, 0, [term_id])

        return expanded

    def _trace_object(self, term_id, relation_dict_name: str, all_onto=True, nerve_only=False):
        """
        Shared logic for tracing object (up or down).
        - relation_dict_name: key in __onto_data to use for relations
        """
        if term_id not in self.__onto_data.get('nerves', []) and nerve_only:
            return {}

        relation_dict = self.__onto_data.get(relation_dict_name, {})

        if all_onto:
            labels = self.__onto_data.get('id_to_labels', {}).get(term_id, [])
            term_ids = {
                tid
                for label in labels
                for tid in self.__onto_data.get('label_to_ids', {}).get(label.lower(), [])
            }
        else:
            term_ids = [term_id]

        relation = {}
        for tid in term_ids:
            traced = self.trace_relation(tid, relation_dict, 0, [term_id])
            relation.update({
                k: v for k, v in traced.items()
                if (k in self.__onto_data.get('nerves', []) and nerve_only) or (not nerve_only)
            })

        return relation


    def trace_nerve_down(self, term_id, consider_subclass_and_part=True, all_onto=True):
        relation_dict_name = (
            'superclass_of_has_parts' if consider_subclass_and_part else 'superclass_of'
        )
        return self._trace_object(term_id, relation_dict_name, all_onto=all_onto, nerve_only=True)


    def trace_nerve_up(self, term_id, consider_superclass_and_part=True, all_onto=True):
        relation_dict_name = (
            'subclass_part_of' if consider_superclass_and_part else 'subclass_of'
        )
        return self._trace_object(term_id, relation_dict_name, all_onto=all_onto, nerve_only=True)

    def trace_subclasses(self, term_id, consider_subclass_and_part=True, all_onto=True):
        relation_dict_name = (
            'superclass_of_has_parts' if consider_subclass_and_part else 'superclass_of'
        )
        return self._trace_object(term_id, relation_dict_name, all_onto)

    def trace_superclasses(self, term_id, consider_superclass_and_part=True, all_onto=True):
        relation_dict_name = (
            'subclass_part_of' if consider_superclass_and_part else 'subclass_of'
        )
        return self._trace_object(term_id, relation_dict_name, all_onto)

    def trace_branch_down(self, term_id, all_onto=True):
        return self._trace_object(term_id, 'has_branches', all_onto)

    def trace_branch_up(self, term_id, all_onto=True):
        return self._trace_object(term_id, 'branch_of', all_onto)

    def trace_part_down(self, term_id, include_branch=False, all_onto=True):
        parts = self._trace_object(term_id, 'has_parts', all_onto)
        if not include_branch:
            for k in self.trace_branch_down(term_id):
                parts.pop(k, None)
        return parts

    def trace_part_up(self, term_id, include_branch=False, all_onto=True):
        parts = self._trace_object(term_id, 'part_of', all_onto)
        if not include_branch:
            for k in self.trace_branch_up(term_id):
                parts.pop(k, None)
        return parts


