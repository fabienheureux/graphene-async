import asyncio

from django.http import HttpResponse, HttpResponseNotAllowed
from django.http.response import HttpResponseBadRequest
from django.utils.decorators import classonlymethod

from graphql import parse, validate
from graphql.execution import ExecutionResult

from graphene_django.settings import graphene_settings
from graphene_django.views import GraphQLView as BaseView, HttpError

from .schema import AuthorLoader

class AsyncGraphQLView(BaseView):
  def get_context(self, request):
    author_loader = AuthorLoader()
    request.dataloaders = {
      "author_loader": author_loader,
    }
    return request

  @classonlymethod
  def as_view(cls, **initkwargs):
    # This code tells django that this view is async, see docs here:
    # https://docs.djangoproject.com/en/3.1/topics/async/#async-views

    view = super().as_view(**initkwargs)
    view._is_coroutine = asyncio.coroutines._is_coroutine
    return view

  async def dispatch(self, request, *args, **kwargs):
    try:
      if request.method.lower() not in ("get", "post"):
        raise HttpError(
          HttpResponseNotAllowed(
            ["GET", "POST"], "GraphQL only supports GET and POST requests."
          )
        )

      data = self.parse_body(request)
      show_graphiql = self.graphiql and self.can_display_graphiql(request, data)

      if show_graphiql:
        return self.render_graphiql(
          request,
            # Dependency parameters.
            whatwg_fetch_version=self.whatwg_fetch_version,
            whatwg_fetch_sri=self.whatwg_fetch_sri,
            react_version=self.react_version,
            react_sri=self.react_sri,
            react_dom_sri=self.react_dom_sri,
            graphiql_version=self.graphiql_version,
            graphiql_sri=self.graphiql_sri,
            graphiql_css_sri=self.graphiql_css_sri,
            subscriptions_transport_ws_version=self.subscriptions_transport_ws_version,
            subscriptions_transport_ws_sri=self.subscriptions_transport_ws_sri,
            # The SUBSCRIPTION_PATH setting.
            subscription_path=self.subscription_path,
            # GraphiQL headers tab,
            graphiql_header_editor_enabled=graphene_settings.GRAPHIQL_HEADER_EDITOR_ENABLED,
        )

      result, status_code = await self.get_response(request, data, show_graphiql)

      return HttpResponse(
        status=status_code, content=result, content_type="application/json"
      )

    except HttpError as e:
      response = e.response
      response["Content-Type"] = "application/json"
      response.content = self.json_encode(
        request, {"errors": [self.format_error(e)]}
      )
      return response

  async def get_response(self, request, data, show_graphiql=False):
    query, variables, operation_name, id = self.get_graphql_params(request, data)

    execution_result = await self.execute_graphql_request(
      request, data, query, variables, operation_name, show_graphiql
    )

    status_code = 200
    if execution_result:
      response = {}

      if execution_result.errors:
        response["errors"] = [
          self.format_error(e) for e in execution_result.errors
        ]

      if execution_result.errors and any(
        not getattr(e, "path", None) for e in execution_result.errors
      ):
        status_code = 400
      else:
        response["data"] = execution_result.data

      result = self.json_encode(request, response, pretty=show_graphiql)
    else:      
      result = None

    return result, status_code

  async def execute_graphql_request(
    self, request, data, query, variables, operation_name, show_graphiql=False
  ):
    if not query:
      if show_graphiql:
        return None
      raise HttpError(HttpResponseBadRequest("Must provide query string."))

    try:
      document = parse(query)
    except Exception as e:
      return ExecutionResult(errors=[e])

    validation_errors = validate(self.schema.graphql_schema, document)
    if validation_errors:
      return ExecutionResult(data=None, errors=validation_errors)

    try:
      extra_options = {}
      if self.execution_context_class:
        extra_options["execution_context_class"] = self.execution_context_class

      options = {
        "source": query,
        "root_value": self.get_root_value(request),
        "variable_values": variables,
        "operation_name": operation_name,
        "context_value": self.get_context(request),
        "middleware": self.get_middleware(request),
      }
      options.update(extra_options)

      return await self.schema.execute_async(**options)
    except Exception as e:
      return ExecutionResult(errors=[e])