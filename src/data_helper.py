import os
import pickle
import sys

import numpy as np
from models.tree import RstTree
import torch
from utils.document import Doc
import nltk
from ubc_coref.loader import Document
from sklearn.model_selection import train_test_split
from ubc_coref import loader
from utils.other import action_map, relation_map
sys.modules['loader'] = loader

class DataHelper(object):
    
    def __init__(self):
        self.action_map = {}
        self.relation_map = {}

    def create_data_helper(self, data_dir, config, coref_trainer):        
        print("Parsing trees")
        
        # read train data
        all_feats_list, self.feats_list = [], []
        all_actions_numeric, self.actions_numeric = [], []
        all_relations_numeric, self.relations_numeric = [], []
        self.docs = []
        self.val_trees = []
        
        print("Generating features")
        for i, rst_tree in enumerate(self.read_rst_trees(data_dir=data_dir)):
            
            feats, actions, relations = rst_tree.generate_action_relation_samples(config)
            fdis = feats[0][0]
            
            # Old doc instance for storing sentence/paragraph/document features
            doc = Doc()
            eval_instance = fdis.replace('.dis', '.merge')
            doc.read_from_fmerge(eval_instance)

            tok_edus = [nltk.word_tokenize(edu) for edu in doc.doc_edus]
            tokens = flatten(tok_edus)
            
            # Coreference resolver document instance for coreference functionality
            # (converting tokens to wordpieces and getting corresponding coref boundaries etc)
            coref_document = Document(raw_text=None, tokens=tokens, sents=tok_edus, 
                                      corefs=[], speakers=["0"] * len(tokens), genre="nw", 
                                      filename=fdis)
            # Duplicate for convenience
            coref_document.token_dict = doc.token_dict
            coref_document.edu_dict = doc.edu_dict
            coref_document.old_doc = doc
            
            for (feat, action, relation) in zip(feats, actions, relations):
                feat[0] = i
                all_feats_list.append(feat)
                all_actions_numeric.append(action)
                all_relations_numeric.append(relation)
                                        
            self.docs.append(coref_document)
            if i % 50 == 0:
                print("Processed ", i + 1, " trees")
                
        actions_numeric = [action_map[x] for x in actions_numeric]
        relations_numeric = [relation_map[x] for x in relations_numeric]
        
        # Stratify by number of EDUs in the document
        stratified = get_stratify_classes([len(coref_document.edu_dict) for coref_document in self.docs])
        train_indexes, val_indexes = train_test_split(np.arange(len(self.docs)), 
                                                          test_size=0.1, random_state=1, stratify=stratified)
        
        # Select only those stack-queue actions that belong to trees in the train set 
        for i, feat in enumerate(all_feats_list):
            if feat[0] in train_indexes:
                self.feats_list.append(feat)
                self.actions_numeric.append(all_actions_numeric[i])
                self.relations_numeric.append(all_relations_numeric[i])
                            
        self.val_trees = [self.docs[index].filename for index in val_indexes]
        self.all_clusters = []
        
        # Pre-generate clusters for all docs (to speed up training)
        with torch.no_grad():
            for i, doc in enumerate(self.docs):
                self.all_clusters.append(coref_trainer.predict_rst(doc)[0])
                print("Coref cluster for document: ", i)
            
    def save_data_helper(self, fname):
        print('Save data helper...')
        data_info = {
            'feats_list': self.feats_list,
            'actions_numeric': self.actions_numeric,
            'relations_numeric': self.relations_numeric,
            'docs': self.docs,
            'val_trees': self.val_trees,
            'all_clusters': self.all_clusters,
        }
        
        with open(fname, 'wb') as fout:
            pickle.dump(data_info, fout)

    def load_data_helper(self, fname):
        print('Load data helper ...')
        with open(fname, 'rb') as fin:
            data_info = pickle.load(fin)
        self.feats_list = data_info['feats_list']
        self.actions_numeric = data_info['actions_numeric']  
        self.relations_numeric = data_info['relations_numeric'] 
        self.val_trees = data_info['val_trees']
        self.docs = data_info['docs']
        self.all_clusters = data_info['all_clusters']
        
    def gen_action_train_data(self, trees):
        return self.feats_list, self.action_seqs_numeric
                
    @staticmethod
    def read_rst_trees(data_dir):
        # Read RST tree file
        files = [os.path.join(data_dir, fname) for fname in os.listdir(data_dir) if fname.endswith('.dis')]
        for i, fdis in enumerate(files):
            fmerge = fdis.replace('.dis', '.merge')
            if not os.path.isfile(fmerge):
                print("Corresponding .fmerge file does not exist. Skipping the file.")
                continue
            rst_tree = RstTree(fdis, fmerge)
            rst_tree.build()
            yield rst_tree
           
        
def flatten(alist):
    """ Flatten a list of lists into one list """
    return [item for sublist in alist for item in sublist]
        
    
def get_stratify_classes(action_labels):
    
    all_classes = np.array([50, 100, 200])
    stratify_classes = [np.sum(action_label > all_classes)
                        for action_label in action_labels]
    return stratify_classes
    
