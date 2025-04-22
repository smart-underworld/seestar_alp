import geocoder
import tzlocal
import datetime


def get_current_gps_coordinates():
    g = geocoder.ip(
        "me"
    )  # this function is used to find the current information using our IP Add
    if g.latlng is not None:  # g.latlng tells if the coordiates are found or not
        return g.latlng
    else:
        return None


if __name__ == "__main__":
    tz_name = tzlocal.get_localzone_name()
    tz = tzlocal.get_localzone()
    now = datetime.datetime.now(tz)
    print(now)
    date_json = {}
    date_json["year"] = now.year
    date_json["mon"] = now.month
    date_json["day"] = now.day
    date_json["hour"] = now.hour
    date_json["min"] = now.minute
    date_json["sec"] = now.second
    date_json["time_zone"] = tz_name

    print(date_json)

    print("Current date and time:")
    print(now.strftime("%Y-%m-%d %H:%M:%S"))

    print()
    print(datetime.datetime.now().astimezone().tzname())
    coordinates = get_current_gps_coordinates()
    if coordinates is not None:
        latitude, longitude = coordinates
        print(f"Your current GPS coordinates are:")
        print(f"Latitude: {latitude}")
        print(f"Longitude: {longitude}")

    else:
        print("Unable to retrieve your GPS coordinates.")
