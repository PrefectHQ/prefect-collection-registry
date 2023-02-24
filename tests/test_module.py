from prefect import flow


@flow
def foo():
    print("what")


@flow
def bar():
    print("is")


def baz():
    print("up")
