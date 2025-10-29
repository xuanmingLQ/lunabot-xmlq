from ...utils import server
def get_suite(region:str, user_id:str,filter:list[str]|None=None):
    return server(
        path="/user/suite",
        method="get",
        params={
            'region':region,
            'userId':user_id,
            'filter':filter
        }
    )
def get_mysekai(region:str, user_id:str,filter:list[str]|None=None):
    return server(
        path="/user/mysekai",
        method="get",
        params={
            'region':region,
            'userId':user_id,
            'filter':filter
        }
    )
def get_profile(region:str, user_id:str):
    return server(
        path="/user/profile",
        method="get",
        params={
            'region':region,
            'userId':user_id,
            'filter':filter
        }
    )