import graphene
from aiodataloader import DataLoader
from asgiref.sync import sync_to_async

from books.models import Book as BookModel, Author as AuthorModel


class Author(graphene.ObjectType):
  name = graphene.String(required=True)

class Book(graphene.ObjectType):
  title = graphene.String(required=True)
  author = graphene.Field(Author, required=True)

  # store book instance on type
  _instance = None

  def __init__(self, _instance=None, **kwargs):
    self._instance = _instance
    super().__init__(**kwargs)
    
  async def resolve_author(self, info):
    author_loader = info.context.dataloaders["author_loader"]

    # Note: we can't do `instance.author.id` because that would cause 
    # Django fetch the author instance, so we're accessing the author_id
    # directly
    author_id = self._instance.author_id
    return await author_loader.load(author_id)

  @classmethod
  def from_instance(cls, instance):
    return cls(
      _instance=instance,
      title=instance.title,
    )

@sync_to_async
def get_all_books():
  return list(BookModel.objects.all())

@sync_to_async
def get_authors(keys):
  qs = AuthorModel.objects.filter(id__in=keys)
  return {author.id: author for author in qs}

class AuthorLoader(DataLoader):
  async def batch_load_fn(self, keys):
    authors = await get_authors(keys)
    return [authors.get(key) for key in keys]

class Query(graphene.ObjectType):
  hello = graphene.String()

  async def resolve_hello(root, info):
    return "world"

  books = graphene.List(Book)

  async def resolve_books(root, info):
    all_books = await get_all_books()
    return [Book.from_instance(book) for book in all_books]

schema = graphene.Schema(Query)