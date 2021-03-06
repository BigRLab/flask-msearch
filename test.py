import datetime
import logging
import unittest
from tempfile import mkdtemp

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_msearch import Search
from sqlalchemy.ext.hybrid import hybrid_property

# do not clutter output with log entries
logging.disable(logging.CRITICAL)

db = None

titles = [
    'watch a movie', 'read a book', 'write a book', 'listen to a music',
    'I have a book'
]


class ModelSaveMixin(object):
    def save(self):
        if not self.id:
            db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()


class SearchTestBase(unittest.TestCase):
    def setUp(self):
        class TestConfig(object):
            SQLALCHEMY_TRACK_MODIFICATIONS = True
            SQLALCHEMY_DATABASE_URI = 'sqlite://'
            DEBUG = True
            TESTING = True
            MSEARCH_INDEX_NAME = mkdtemp()
            # MSEARCH_BACKEND = 'whoosh'

        self.app = Flask(__name__)
        self.app.config.from_object(TestConfig())
        # we need this instance to be:
        #  a) global for all objects we share and
        #  b) fresh for every test run
        global db
        db = SQLAlchemy(self.app)
        self.search = Search(self.app, db=db)
        self.Post = None

    def init_data(self):
        if self.Post is None:
            self.fail('Post class not defined')
        with self.app.test_request_context():
            db.create_all()
            for (i, title) in enumerate(titles, 1):
                post = self.Post(title=title, content='content%d' % i)
                post.save()

    def tearDown(self):
        with self.app.test_request_context():
            db.drop_all()
            db.metadata.clear()


class TestMixin(object):
    def test_basic_search(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('book').all()
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0].title, titles[1])
            self.assertEqual(results[1].title, titles[2])
            results = self.Post.query.msearch('movie').all()
            self.assertEqual(len(results), 1)

    def test_search_limit(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('book', limit=2).all()
            self.assertEqual(len(results), 2)

    def test_boolean_operators(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('book movie', or_=False).all()
            self.assertEqual(len(results), 0)
            results = self.Post.query.msearch('book movie', or_=True).all()
            self.assertEqual(len(results), 4)

    def test_delete(self):
        with self.app.test_request_context():
            self.Post.query.filter_by(title='read a book').delete()
            results = self.Post.query.msearch('book').all()
            self.assertEqual(len(results), 2)

    def test_update(self):
        with self.app.test_request_context():
            post = self.Post.query.filter_by(title='write a book').one()
            post.title = 'write a novel'
            post.save()
            results = self.Post.query.msearch('book').all()
            self.assertEqual(len(results), 2)


class TestSearch(TestMixin, SearchTestBase):
    def setUp(self):
        super(TestSearch, self).setUp()

        class Post(db.Model, ModelSaveMixin):
            __tablename__ = 'basic_posts'
            __searchable__ = ['title', 'content']

            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(49))
            content = db.Column(db.Text)

            def __repr__(self):
                return '<Post:{}>'.format(self.title)

        self.Post = Post
        self.init_data()

    def test_field_search(self):
        with self.app.test_request_context():
            title1 = 'add one user'
            content1 = 'add one user content 1'
            title2 = 'add two user'
            content2 = 'add two content 2'
            post1 = self.Post(title=title1, content=content1)
            post1.save()

            post2 = self.Post(title=title2, content=content2)
            post2.save()

            results = self.Post.query.msearch('user').all()
            self.assertEqual(len(results), 2)

            results = self.Post.query.msearch('user', fields=['title']).all()
            self.assertEqual(len(results), 2)

            results = self.Post.query.msearch('user', fields=['content']).all()
            self.assertEqual(len(results), 1)


class TestRelationSearch(TestMixin, SearchTestBase):
    def setUp(self):
        super(TestRelationSearch, self).setUp()

        class Tag(db.Model, ModelSaveMixin):
            __tablename__ = 'tag'

            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(49))

            def msearch_post_tag(self, delete=False):
                from sqlalchemy import text
                sql = text('select id from post where tag_id=' + str(self.id))
                return {
                    'attrs': [{
                        'id': str(i[0]),
                        'tag.name': self.name
                    } for i in db.engine.execute(sql)],
                    '_index': Post
                }

        class Post(db.Model, ModelSaveMixin):
            __tablename__ = 'post'
            __searchable__ = ['title', 'content', 'tag.name']

            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(49))
            content = db.Column(db.Text)

            # one to one
            tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'))
            tag = db.relationship(
                Tag, backref=db.backref(
                    'post', uselist=False), uselist=False)

            def __repr__(self):
                return '<Post:{}>'.format(self.title)

        self.Post = Post
        self.Tag = Tag
        self.init_data()

    def test_field_search(self):
        with self.app.test_request_context():
            title1 = 'add one user'
            content1 = 'add one user content 1'
            title2 = 'add two user'
            content2 = 'add two content 2'

            post1 = self.Post(title=title1, content=content1)
            post1.save()

            tag1 = self.Tag(name='tag hello1', post=post1)
            tag1.save()

            post2 = self.Post(title=title2, content=content2)
            post2.save()

            tag2 = self.Tag(name='tag hello2', post=post2)
            tag2.save()

            results = self.Post.query.msearch('tag').all()
            self.assertEqual(len(results), 2)

            results = self.Post.query.msearch('tag', fields=['title']).all()
            self.assertEqual(len(results), 0)

            results = self.Post.query.msearch('tag', fields=['tag.name']).all()
            self.assertEqual(len(results), 2)

            tag1.name = 'post hello1'
            tag1.save()

            results = self.Post.query.msearch('tag', fields=['tag.name']).all()
            self.assertEqual(len(results), 1)

            tag1.name = 'post tag'
            tag1.save()

            results = self.Post.query.msearch('tag', fields=['tag.name']).all()
            self.assertEqual(len(results), 2)


class TestSearchHybridProp(TestMixin, SearchTestBase):
    def setUp(self):
        super(TestSearchHybridProp, self).setUp()

        class PostHybrid(db.Model, ModelSaveMixin):
            __tablename__ = 'hybrid_posts'
            __searchable__ = ['fts_text']

            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(49))
            content = db.Column(db.Text)

            @hybrid_property
            def fts_text(self):
                return ' '.join([self.title, self.content])

            @fts_text.expression
            def fts_text(cls):
                # sqlite don't support concat
                # return db.func.concat(cls.title, ' ', cls.content)
                return cls.title.op('||')(' ').op('||')(cls.content)

            def __repr__(self):
                return '<Post:{}>'.format(self.title)

        self.Post = PostHybrid
        self.init_data()

    def test_field_search(self):
        with self.app.test_request_context():
            title1 = 'add one user'
            content1 = 'add one user content 1'
            title2 = 'add two user'
            content2 = 'add two content 2'
            post1 = self.Post(title=title1, content=content1)
            post1.save()

            post2 = self.Post(title=title2, content=content2)
            post2.save()

            results = self.Post.query.msearch('user').all()
            self.assertEqual(len(results), 2)


class TestHybridPropTypeHint(SearchTestBase):
    def setUp(self):
        super(TestHybridPropTypeHint, self).setUp()

        class Post(db.Model, ModelSaveMixin):
            __tablename__ = 'posts'
            __searchable__ = ['fts_int', 'fts_date']

            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(20))
            int1 = db.Column(db.Integer)
            int2 = db.Column(db.Integer)

            @hybrid_property
            def fts_int(self):
                return self.int1 + self.int2

            fts_int.type_hint = 'integer'

            @fts_int.expression
            def fts_int(cls):
                return db.func.sum(cls.int1, cls.int2)

            @hybrid_property
            def fts_date(self):
                return max(
                    datetime.date(2017, 5, 4), datetime.date(2017, 5, 3))

            fts_date.type_hint = 'date'

            @fts_date.expression
            def fts_date(cls):
                return db.func.max(
                    datetime.date(2017, 5, 4), datetime.date(2017, 5, 3))

            def __repr__(self):
                return '<Post:{}>'.format(self.name)

        self.Post = Post
        with self.app.test_request_context():
            db.create_all()
            for i in range(10):
                name = 'post %d' % i
                post = self.Post(name=name, int1=i, int2=i * 2)
                post.save()

    def test_int_prop(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('0', fields=['fts_int']).all()
            assert len(results) == 1
            results = self.Post.query.msearch('27', fields=['fts_int']).all()
            assert len(results) == 1

    def test_date_prop(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch(
                '2017-05-04', fields=['fts_date']).all()
            assert len(results) == 10


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromNames([
        'test.TestSearch',
        'test.TestRelationSearch',
        'test.TestSearchHybridProp',
        'test.TestHybridPropTypeHint',
    ])
    unittest.TextTestRunner(verbosity=1).run(suite)
