from src.utils import download_data
def download_rip_assets(region:str,path:str):
    return download_data(
        path="/rip/downloadAssets",
        params=[region, path]
    )