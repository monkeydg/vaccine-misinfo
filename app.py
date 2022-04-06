"""
Created by David Gallo (https://github.com/monkeydg/)

Vaccine Misinformation Checker

This code is a machine learning server to classify text or tweets as vaccine misinformation.
The API server is run with Flask and deployed on AWS with Zappa. 
Hyperparameters were tuned using Gridsearch. The infrastructure is still in the code however to 
use or test different classifiers.
"""

import numpy as np
import pandas as pd
import sys
import re
import os
import string
import pickle
from flask import Flask, jsonify, request
import tweepy
import logging
from dotenv import load_dotenv

logging.basicConfig(filename='predictions.log', level=logging.INFO)

from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import GaussianNB
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble  import GradientBoostingClassifier, AdaBoostClassifier
# from sklearn.svm import SVC
# from sklearn.neighbors import KNeighborsClassifier

import nlpaug.augmenter.word as naw
import nltk
nltk.download('stopwords')
nltk.download('wordnet')
nltk.download('averaged_perceptron_tagger')
nltk.download('omw-1.4')
nltk.download('punkt')
from nltk import word_tokenize
from nltk.corpus import stopwords

# Paths
CLF_PKL_PATHS = [
    "./pkls/classifiers/g_clf.pkl",
    "./pkls/classifiers/l_clf.pkl",
    "./pkls/classifiers/k_clf.pkl",
    "./pkls/classifiers/rf_clf.pkl",
    "./pkls/classifiers/dt_clf.pkl",
    "./pkls/classifiers/gb_clf.pkl",
    "./pkls/classifiers/sgd_clf.pkl",
    "./pkls/classifiers/ab_clf.pkl"
    ]
DATA_PATH = './data/tweets.csv'
SCORES_PATH = './pkls/scores.pkl'
CLF_PARAMS_PATH = './pkls/params.pkl'
CV_PKL_PATH = './pkls/cv.pkl'
DOTENV_PATH = '.env'

load_dotenv()
CONSUMER_KEY = os.environ.get("CONSUMER_KEY")
CONSUMER_SECRET = os.environ.get("CONSUMER_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")

class Classifier:
    """Python object representing a machine learning classifier and its training results"""
    def __init__(self, classifier, name, shortname):
        self.classifier = classifier
        self.name = name
        self.shortname = shortname
        self.train_accuracy = None
        self.test_accuracy = None
        self.precision = None
        self.recall = None
        self.f1 = None

    @property
    def scores(self):
        """Returns a classifier's comabined scores as a dict after evaluating a model"""
        try:
            return {
                "Train accuracy": self.train_accuracy,
                "Test accuracy": self.test_accuracy,
                "Precision": self.precision,
                "Recall": self.recall,
                "F1": self.f1
                }
        except:
            return None  # if scores haven't been initialized

    def evaluate(self, features, labels, num_iters=3, test_size=0.2):
        """Evaluates a classifier's accuracy, precision, recall, and F1 score"""
        train_accuracy = []
        test_accuracy = []
        precision = []
        recall = []
        f1 = []
        first = True
        for i in range(num_iters):
            features_train, features_test, labels_train, labels_test =\
                train_test_split(features, labels, test_size=test_size)
            self.classifier.fit(features_train, labels_train)
            predictions_train = self.classifier.predict(features_train)
            predictions = self.classifier.predict(features_test)
            train_accuracy.append(accuracy_score(labels_train, predictions_train))
            test_accuracy.append(accuracy_score(labels_test, predictions))
            precision.append(precision_score(labels_test, predictions))
            recall.append(recall_score(labels_test, predictions))
            f1.append(f1_score(labels_test, predictions))
            if first:
                sys.stdout.write('\nProcessing')
            sys.stdout.write('.')
            sys.stdout.flush()
            first = False

        self.train_accuracy = np.mean(train_accuracy)
        self.test_accuracy = np.mean(test_accuracy)
        self.precision = np.mean(precision)
        self.recall = np.mean(recall)
        self.f1 = np.mean(f1)
        self.show_results()

    def show_results(self):
        """Pretty-prints the results of the evaluate() method"""
        print (self.classifier)
        print (f"Training accuracy: \t{self.train_accuracy}")
        print (f"Testing accuracy: \t{self.test_accuracy}")
        print (f"Precision: \t\t{self.precision}")
        print (f"Recall: \t\t{self.recall}")
        print (f"F1: \t\t\t{self.f1}")

def import_data(path, split_on=';'):
    """Imports data from a csv file and returns a pandas dataframe"""
    return pd.read_csv(path, delimiter=split_on, encoding= 'unicode_escape')

def remove_stopwords(text):
    """Removes stopwords from text that appear in nltk.corpus's stopwords list"""
    cleaned_text = [word for word in text if word not in stopwords.words('english')]
    return cleaned_text

def clean_text(text):
    """Manually clean text to remove punctuation, special characters, and numbers"""
    text = str(text).lower()
    text = re.sub('\[.*?\]', '', text)
    text = re.sub('https?://\S+|www\.\S+', '', text)
    text = re.sub('<.*?>+', '', text)
    text = re.sub('[%s]' % re.escape(string.punctuation), '', text)
    text = re.sub('\n', '', text)
    text = re.sub('\r', '', text)
    text = re.sub('\w*\d\w*', '', text)
    text = text.encode("ascii", "ignore").decode()
    return text

def stem(text):
    """Stems text using nltk's SnowballStemmer"""
    stemmer = nltk.SnowballStemmer("english")
    stemmed_text = [stemmer.stem(word) for word in text]
    return stemmed_text

def dummy(doc):
    """Helper function for our vectorizer to prevent unneeded preprocessing"""
    return doc

def vectorize(tokens):
    """Fits and transforms a CountVectorizer on training data"""
    cv = CountVectorizer(tokenizer=dummy, preprocessor=dummy)
    vectors = cv.fit_transform(tokens).toarray()
    return vectors, cv

def preprocess_data(df):
    """Cleans data from our training dataset and prepares it in a dataframe"""
    # Dropping the ID column
    df = df.drop(["id"],axis=1)

    # Renaming the columns
    df.set_axis(['is_misinfo', 'text'], axis=1, inplace=True)

    # Correcting data imbalance using synonyms for tweets with misinformation
    tweetaug = []
    for row in df[df["is_misinfo"] == 1]["text"]:
        aug = naw.SynonymAug(aug_src='wordnet', aug_min=3)
        tw = aug.augment(row, n=1)
        tweetaug.append(tw)
    tweetaug = pd.DataFrame(tweetaug, columns = ['text'])
    tweetaug['is_misinfo'] = 1
    df = pd.concat([df, tweetaug])

    # Clean text, tokenize, remove stopwords, and stem text
    df['text'] = df['text'].apply(clean_text)
    df['text'] = df['text'].apply(word_tokenize)
    df['text'] = df['text'].apply(remove_stopwords)
    df['text'] = df['text'].apply(stem)
    return df

def run_models(features, labels):
    """
    Builds and runs a series of models to predict whether a tweet is misinfo or not.
    Hyperparameter tuning was compelted using Gridsearch to find the best parameters for each model.
    """
    g_clf = Classifier(
        GaussianNB(var_smoothing= 0.001),
        "Gaussian Naive Bayes",
        "g_clf"
        )
    g_clf.evaluate(features, labels)

    l_clf = Classifier(
        LogisticRegression(
            C=1.7575106248547894,
            class_weight='balanced',
            penalty='l2',
            solver='newton-cg'
            ),
        "Logistic Regression",
        "l_clf"
        )
    l_clf.evaluate(features, labels)

    k_clf = Classifier(
        KMeans(n_clusters=2, tol=0.001),
        "K-Means Clustering",
        "k_clf"
        )
    k_clf.evaluate(features, labels)

    # Too memory intensive, removed:
    # s_clf = Classifier(
    #     SVC(C=10, gamma=0.01),
    #     "Support Vector Machine",
    #     "s_clf"
    #     )
    # s_clf.evaluate(features, labels)

    rf_clf = Classifier(
        RandomForestClassifier(
            bootstrap=False,
            max_depth=15,
            max_features=9,
            n_estimators=300,
            min_samples_split=3
            ),
        "Random Forest",
        "rf_clf"
        )
    rf_clf.evaluate(features, labels)

    dt_clf = Classifier(
        DecisionTreeClassifier(
            criterion='gini',
            max_depth=None,
            min_samples_leaf=1,
            min_samples_split=200
            ),
        "Decision Tree",
        "dt_clf"
        )
    dt_clf.evaluate(features, labels)

    gb_clf = Classifier(
        GradientBoostingClassifier(
            learning_rate=0.04,
            max_depth=10,
            n_estimators=1500,
            subsample=0.2
            ),
        "Gradient Boosting",
        "gb_clf"
        )
    gb_clf.evaluate(features, labels)

    sgd_clf = Classifier(
        SGDClassifier(loss="modified_huber", penalty="l2", alpha=0.01),
        "Stochastic Gradient Descent",
        "sgd_clf"
        )
    sgd_clf.evaluate(features, labels)

    ab_clf = Classifier(
        AdaBoostClassifier(learning_rate=1.0, n_estimators=500),
        "AdaBoost",
        "ab_clf"
        )
    ab_clf.evaluate(features, labels)

    # Too memory intensive, removed:
    # knn_clf = Classifier(
    #     KNeighborsClassifier(n_neighbors=3, metric='manhattan', weights='distance'),
    #     "K-Nearest Neighbors",
    #     "knn_clf"
    #     )
    # knn_clf.evaluate(features, labels)

    return [g_clf, l_clf, k_clf, rf_clf, dt_clf, gb_clf, sgd_clf, ab_clf]

def preprocess_query(text, cv):
    """Cleans, tokenizes, removes stopwords, and stems text. Then, fits a vectorizer"""
    text = clean_text(text)
    text = word_tokenize(text)
    text = remove_stopwords(text)
    text = stem(text)

    vectors = cv.transform([text])
    vectors = vectors.toarray() # we convert the sparse matrix to a dense array for prediction
    return vectors

def test_pickles(clf_paths, cv_path):
    """Loads the classifiers and vectorizer into memory from pickle files"""
    pickle.load(open(cv_path, "rb"))

    for clf_path in clf_paths:
        pickle.load(open(clf_path, "rb"))

def init(scores_path, cv_path, data_path, clf_params_path):
    """Trains the classifiers and dumps the vectorizer and classifiers into pickle files"""
    df = import_data(data_path)
    df = preprocess_data(df)
    df_labels = df["is_misinfo"]

    vectors, cv = vectorize(df["text"])
    lst_clfs = run_models(vectors, df_labels)

    # dump our scores as a dataframe pkl
    df_scores = pd.DataFrame(
        data=[clf.scores for clf in lst_clfs],
        index=[clf.name for clf in lst_clfs],
        columns=["Test accuracy", "Precision", "Recall", "F1"]
        )
    df_scores["shortname"] = [clf.shortname for clf in lst_clfs]
    df_scores.to_pickle(scores_path)

    # dump our classifiers as pkls
    for clf in lst_clfs:
        pickle.dump(clf, open(f"{clf.shortname}.pkl", "wb"))
    
    # dump our classifiers parameters dataframe as a pkl
    df_clf_params = pd.DataFrame(
        data=[str(clf.classifier) for clf in lst_clfs],
        index=[clf.name for clf in lst_clfs],
        columns=["Parameters"] 
        )
    df_clf_params.to_pickle(clf_params_path)

    # dump our vectorizer as a pkl
    pickle.dump(cv, open(cv_path, "wb"))

def scrape_tweet(url):
    """Extracts the text from a given tweet url using Tweepy"""
    auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
    auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    api = tweepy.API(auth)
    try:
        # the ID of the status
        tweet_id = url.split('/')[-1].split('?')[0]

        # fetching the status
        status = api.get_status(tweet_id, tweet_mode = "extended")

        # fetching the text attribute
        return status.full_text
    except: 
        # if there's an error, we just abort and return nothing
        return None

app = Flask(__name__)

@app.route("/predict", methods=['GET'])
def get_prediction():
    """
    Returns a json object with the results of a prediction, sent via query string
    with arguments ?url= or ?text=
    Returns Bad URL if the url can't be parsed with Tweepy,
    NA if no text is provided,
    1 for predicted misinformation, and
    0 for predictied non-misinformation
    """
    # parses the query string with the text/url to be classified
    selected_clf = request.args.get('clf')
    if not selected_clf:
        selected_clf = "ab_clf"  # defaults to adaboost if no classifier is provided
    text = request.args.get('text')
    url = request.args.get('url')
    if url:
        text = scrape_tweet(url)
        if not text:
            return jsonify(is_misinformation="Bad URL")

    if not text:
        return jsonify(is_misinformation="NA")

    # loads the classifier and vectorizer from pickle files
    cv = pickle.load(open(CV_PKL_PATH, "rb"))
    clf = pickle.load(open(f"{selected_clf}.pkl", "rb"))
    features = preprocess_query(text, cv)

    # returns 0 or 1, predicting misinformation or not
    prediction = int(clf.classifier.predict(features))
    logging.info(f"Predicted {str(prediction)} for string:\n{text}")

    return jsonify(is_misinformation=prediction)

try:
    test_pickles(CLF_PKL_PATHS, CV_PKL_PATH)
    logging.info("CountVectorizer and Classifiers pickles successfully tested")
    print("CountVectorizer and Classifiers pickles successfully tested, listening...")
except:
    print("Unable to load pickles, training new classifiers...") # to delete
    logging.warning("Unable to load pickles, training new classifiers...")
    init(SCORES_PATH, CV_PKL_PATH, DATA_PATH, CLF_PARAMS_PATH)

if __name__ == '__main__':
    app.run()