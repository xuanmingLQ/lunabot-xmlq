from ...utils import server
def get_ranking(region:str,event_id:str):
    return server(
        path="/event/ranking",
        method='get',
        params={
            'region':region,
            'eventId':event_id
        }
    )