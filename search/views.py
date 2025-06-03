import string

from django.shortcuts import render
from threading import Thread, Lock
from time import sleep
from concurrent.futures import ThreadPoolExecutor
from . import models
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin, urlparse
import mysql.connector
from bs4.element import Comment
from django.http import HttpResponse
from django.shortcuts import redirect

# for classification

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import roc_auc_score
from sklearn.metrics import accuracy_score, precision_score, recall_score
from sklearn.metrics import confusion_matrix
from sklearn import svm

# for query
from nltk.corpus import stopwords
from nltk.corpus import wordnet
from django.db.models.expressions import RawSQL
from django.core.paginator import Paginator
import time

# ensure_migrations
from django.core.management import call_command
from django.db import OperationalError

def ensure_migrations():
    try:
        call_command('makemigrations', interactive=False)
        call_command('migrate', interactive=False)
    except OperationalError as e:
        print(f"Migration error: {e}")


# Create your views here.
class MTCrawler:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=20)
        self.to_crawlLock = Lock()
        self.niveLock = Lock()
        self.clfLock = Lock()
        # self.connection_pool = mysql.connector.connect(pool_name="pynative_pool",
        #                                                pool_size=20,
        #                                                pool_reset_session=True,
        #                                                host='localhost',
        #                                                database='search',
        #                                                user='root',
        #                                                password='')
        self.UnVisited = models.UnVisitedPageSet.objects.all().order_by('id')
        training_data = pd.read_csv('trainData_v2.csv')
        training_data["label"] = 9 * [0] + 7 * [1] + 5 * [2] + 9 * [3] + 6 * [4] + 6 * [5] + 9 * [6]
        x_train = np.array(training_data["doc"])
        y_train = np.array(training_data["label"])

        self.cv = CountVectorizer(max_features=2 ** 18, strip_accents='ascii',
                                  token_pattern=u'(?ui)\\b\\w*[a-z]+\\w*\\b', lowercase=True, stop_words='english')
        self.tfidf = TfidfVectorizer()
        x_train_cv = self.cv.fit_transform(x_train)
        x_train_for_occ = self.tfidf.fit_transform(x_train)

        self.naive_bayes = MultinomialNB()
        self.naive_bayes.fit(x_train_cv, y_train)

        self.clf = svm.OneClassSVM(gamma='auto')
        self.clf.fit(x_train_for_occ)

    def tag_visible(self, element):
        if element.parent.name in ['style', 'script', 'head', 'title', 'meta', '[document]']:
            return False
        if isinstance(element, Comment):
            return False
        return True

    def is_valid(self, url):
        parsed = urlparse(url)
        return bool(parsed.netloc) and bool(parsed.scheme)

    def parse_links_info(self, html, url):
        print("hellowww")
        soup = BeautifulSoup(html, 'lxml')
        print("hellowww2")
        if soup.title != None:
            print("hellowww3")
            title = str(soup.title.string)

            texts = soup.findAll(text=True)
            visible_texts = filter(self.tag_visible, texts)
            text_from_html = u" ".join(t.strip() for t in visible_texts)

            x_test = np.array([text_from_html])

            self.clfLock.acquire()
            x_test_for_occ = self.tfidf.transform(x_test)
            is_or_not = self.clf.predict(x_test_for_occ)
            self.clfLock.release()

            self.niveLock.acquire()
            x_test_cv = self.cv.transform(x_test)
            predictions = self.naive_bayes.predict(x_test_cv)
            self.niveLock.release()

            if is_or_not[0] == 1:
                clas = int(predictions[0])

                paragraph = ""
                p = soup.find("p")
                if p != None:
                    paragraph = p.text.strip()
                while len(paragraph) == 0:
                    if p == None or p.find_next("p") == None:
                        break
                    p = p.find_next("p")
                    paragraph = p.text.strip()

                if len(paragraph) > 255:
                    paragraph = paragraph[:255] + "..."
                keywords = title
                for heading in soup.find_all("h1"):
                    keywords = keywords + ' ' + heading.text.strip()

                for tag in soup.find_all('meta'):
                    if 'name' in tag.attrs.keys() and tag.attrs['name'].strip().lower() in ['description', 'keywords']:
                        keywords = keywords + ' ' + tag.attrs['content'].strip()
                print(title)
                models.Sites(class_field=clas, title=title, url=url, keywords=keywords, first_par=paragraph).save()
            else:
                pass

        for a_tag in soup.findAll("a"):
            href = a_tag.attrs.get("href")
            if href == "" or href is None:
                continue
            href = urljoin(url, href)
            parsed_href = urlparse(href)
            # remove URL GET parameters, URL fragments, etc.
            href = parsed_href.scheme + "://" + parsed_href.netloc + parsed_href.path
            if not self.is_valid(href):
                continue
            if not models.VisitedPageSet.objects.filter(url=href):
                self.to_crawlLock.acquire()
                models.UnVisitedPageSet(url=href).save()
                self.to_crawlLock.release()

    def scrape_page(self, url):

        try:
            res = requests.get(url, timeout=(3, 30))

        except requests.RequestException:
            print(requests.RequestException)
            return
        if res and res.status_code == 200 and (
                "text/html" in res.headers["content-type"] or "application/pdf" in res.headers["content-type"]):
            print(res.text)
            self.parse_links_info(res.text, url)

        return True

    def run_scraper(self):
        with self.pool as ex:
            while True:
                try:
                    url = models.UnVisitedPageSet.objects.all().order_by('id')[0]
                    print(url.url)
                    if not models.VisitedPageSet.objects.filter(url=url.url):
                        models.VisitedPageSet(url=url.url).save()
                        url.delete()
                        ex.submit(self.scrape_page, url.url)
                    else:
                        url.delete()
                except Exception as e:
                    # print(e)
                    continue


def crawler():
    crawl = MTCrawler()
    crawl.run_scraper()


# T = Thread(target=crawler)
# T.setDaemon(True)
# T.start()


def index(request):
    # s = models.UnVisitedPageSet(url='https://www.learn-c.org/')
    # s.save()
    ensure_migrations()
    return render(request, 'index.html')


all_classes = [{"name": "Artificial Intelligence", "num": 0},
               {"name": "Graphical visualization", "num": 1},
               {"name": "Software Engineering", "num": 2},
               {"name": "Architecture And OS", "num": 3},
               {"name": "Network", "num": 4},
               {"name": "Database", "num": 5},
               {"name": "Data Structure And Algorithm", "num": 6}]


def result(request):
    if request.method == 'GET':
        # get query
        tin = time.time_ns()
        Q = request.GET.get('query')

        if request.GET.get('filter'):
            fil = request.GET.get('filter')
            print(fil)
            for d in all_classes:
                if d['name'] ==  fil :
                    fil = d['num']

            query = request.GET.get('query')
            if query is None:
                return redirect('/')
            # change query to lower case
            query = str(query).lower()
            # remove symbols
            query = query.translate(str.maketrans('', '', string.punctuation))
            # split
            word_tokens = query.split()
            # remove step words
            stop_words = set(stopwords.words("english"))
            filtered_sentence = [w for w in word_tokens if not w in stop_words]
            # print(filtered_sentence)

            synonyms = set([])

            count = 0
            for x in filtered_sentence:
                for syn in wordnet.synsets(x):
                    for l in syn.lemmas():
                        if (count < 3):
                            if l.name() not in synonyms:
                                synonyms.add(l.name())
                                count += 1
                        else:
                            break
                synonyms.add(x)
                count = 0

            synonyms_string = ' '.join(list(synonyms))
            print(synonyms_string)
            query = synonyms_string.split()
            print(query)
            # site_from_title = models.Sites.objects.filter(title__search=Q)
            # print(site_from_title)
            l = []
            print(fil)
            matched_sites = (

                models.Sites.objects.filter(
                    id__in=RawSQL(
                        f"(SELECT id from search.sites WHERE MATCH(title,keywords,first_par) AGAINST( %s IN NATURAL LANGUAGE MODE ) and class = {fil} )",
                        [Q])).exclude(id__in=l)
            )
            print(matched_sites)
            ac = False
            if not matched_sites:
                matched_sites = (

                    models.Sites.objects.filter(
                        id__in=RawSQL(
                            f"(SELECT id from search.sites WHERE MATCH(title,keywords,first_par) AGAINST( %s IN NATURAL LANGUAGE MODE ) and class = {fil} )",
                            [synonyms_string])).exclude(id__in=l)
                )
                ac = True
            pg = Paginator(matched_sites, 4)
            pg_number = request.GET.get('page')
            page_sites = pg.get_page(pg_number)

        else:
            query = request.GET.get('query')
            if query is None:
                return redirect('/')
            # change query to lower case
            query = str(query).lower()
            # remove symbols
            query = query.translate(str.maketrans('', '', string.punctuation))
            # split
            word_tokens = query.split()
            # remove step words
            stop_words = set(stopwords.words("english"))
            filtered_sentence = [w for w in word_tokens if not w in stop_words]
            # print(filtered_sentence)

            synonyms = set([])

            count = 0
            for x in filtered_sentence:
                for syn in wordnet.synsets(x):
                    for l in syn.lemmas():
                        if (count < 3):
                            if l.name() not in synonyms:
                                synonyms.add(l.name())
                                count += 1
                        else:
                            break
                synonyms.add(x)
                count = 0

            synonyms_string = ' '.join(list(synonyms))
            print(synonyms_string)
            query = synonyms_string.split()
            print(query)
            # site_from_title = models.Sites.objects.filter(title__search=Q)
            # print(site_from_title)
            l = []
            matched_sites = (

                models.Sites.objects.filter(
                    id__in=RawSQL(
                        "(SELECT id from search.sites WHERE MATCH(title,keywords,first_par) AGAINST( %s IN NATURAL LANGUAGE MODE ))",
                        [Q])).exclude(id__in=l)
            )
            print(matched_sites)
            ac = False
            if not matched_sites:
                matched_sites = (

                    models.Sites.objects.filter(
                        id__in=RawSQL(
                            "(SELECT id from search.sites WHERE MATCH(title,keywords,first_par) AGAINST( %s IN NATURAL LANGUAGE MODE ))",
                            [synonyms_string])).exclude(id__in=l)
                )
                ac = True

            pg = Paginator(matched_sites, 4)
            pg_number = request.GET.get('page')
            page_sites = pg.get_page(pg_number)

    # bacause make 2 page for 4 item we separet them into 2 parts
    if len(matched_sites) % 4 == 0:
        pagelen = (len(matched_sites) // 4) + 1
    else:
        pagelen = (len(matched_sites) // 4) + 2


    return render(request, 'result.html', {
        "sites": page_sites,
        'lenthofsites': range(1, pagelen),
        'lenresult': len(matched_sites),
        'resulttime': '%.5f' % ((time.time_ns() - tin) / 10e9),
        'noacure': ac,
        'synonymsstring':synonyms_string.replace(' ' , ' , ')

    })
