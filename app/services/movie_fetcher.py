import requests


def data_parser(data):
    results=[]
    movie_list=data["results"]
    for movie in movie_list:
        details={}
        details["thumbnail"]=f"https://image.tmdb.org/t/p/w342{movie["poster_path"]}"
        details["title"]=movie["original_title"]
        details["lang"]=movie["original_language"]
        details["overview"]=movie["overview"]
        results.append(details)
    return results

def search_movie_torrent(q:str):
    url=f"https://en.yts.lu/browse-movies?api=search&mode=movie&q={q}&page=1"
    response=requests.get(url)
    return {"status":response.status_code,
        "results":data_parser(response.json())}

def get_movie_torrent(title:str):
    url=f"https://en.yts.lu/browse-movies?api=torrents&mode=movie&name={title}&quality=all"
    response=requests.get(url)
    return {
        "status":response.status_code,
        "results":response.json()["hits"]