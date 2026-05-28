from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """
    Consistent pagination across all list endpoints.

    Response shape:
      { count, total_pages, next, previous, results: [...] }

    Clients can override page size with ?page_size=N (max 200).
    We cap at 200 to prevent runaway queries. Large exports should
    use a dedicated export endpoint, not pagination.
    """
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    page_query_param = "page"

    def get_paginated_response(self, data):
        return Response({
            "count":       self.page.paginator.count,
            "total_pages": self.page.paginator.num_pages,
            "next":        self.get_next_link(),
            "previous":    self.get_previous_link(),
            "results":     data,
        })

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count":       {"type": "integer"},
                "total_pages": {"type": "integer"},
                "next":        {"type": "string", "nullable": True},
                "previous":    {"type": "string", "nullable": True},
                "results":     schema,
            },
        }
