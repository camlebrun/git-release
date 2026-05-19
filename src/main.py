import functions_framework
from flask import Request, Response


@functions_framework.http
def main(request: Request) -> Response:
    return Response("OK", status=200)
