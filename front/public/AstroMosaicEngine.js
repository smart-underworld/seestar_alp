/*************************************************************************\
 * 
 *      AstroMosaic telescope planner engine. (C) Jarmo Ruuth, 2018-2021
 *
 * An embeddable JavaScript file of AstroMosaic engine. 
 * It can show:
 *      - Target with telescope field of view using Aladin Lite
 *      - Target day visibility graphs
 *      - Target year visibility graphs
 * 
\*************************************************************************/

/*************************************************************************
 * 
 *      AstroMosaicEngine
 * 
 * AstroMosaic entry point for embedded Javascript.
 * 
 * Notes:
 * - If calling AstroMosaicEngine multiple times Aladin view may show
 *   multiple views. This can be solved by setting AstroMosaicEngine
 *   return object to null before calling it again.
 * 
 * Parameters:
 *
 *      target
 *          Image target as a name, coordinates or a comma 
 *          Separated list of coordinates.
 *
 *      params
 *          Parameters in JSON format for showing the requested view
 *          or views.
 *          {
 *              fov_x            : x fov in degrees,
 *              fov_y            : y fov in degrees,
 *              grid_type        : grid type, "fov" or "mosaic", if not set, "fov" is used,
 *              grid_size_x      : number of grid panels in x direction, if not set, 1 is used
 *              grid_size_y      : number of grid panels y direction, if not set, 1 is used
 *              grid_overlap     : grid overlap in percentage, if not set, 20 is used
 *              location_lat     : location latitude,
 *              location_lng     : location longitude,
 *              horizonSoft      : soft horizon limit or null,
 *              horizonHard      : hard horizon limit or null,
 *              meridian_transit : meridian transit or null,
 *              UTCdate_ms       : start of day UTC date in milliseconds 
 *                                 or null for current day,
 *              timezoneOffset   : difference between UTC time and local time, in hours,
 *                                 null for UTC, should match with lat/lng
 *              isCustomMode     : true to use custom colors, false otherwise
 *                                 if true, all custom colors below must be given,
 *              chartTextColor   : custom chart text color,
 *              gridlinesColor   : custom chart grid lines color,
 *              backgroundColor  : custom chart background color
 *         }
 *
 *      target_div
 *            Div section name for showing the target view, or null.
 *
 *      day_div
 *            Div section name for showing the day visibility view, or null.
 *
 *      year_div
 *            Div section name for showing the year visibility view, or null.
 *
 *      radec_div
 *            Div section name for showing target coordinates, or mosaic panel coordinates.
 * 
 * Requirements:
 *
 *      Aladin Lite needs the following CSS to be loaded::
 *      <link rel="stylesheet" href="https://aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.css" / >
 *
 *      Aladin Lite needs the following scripts to be loaded:
 *      <script type="text/javascript" src="https://code.jquery.com/jquery-1.12.1.min.js" charset="utf-8">< /script>
 *      <script type="text/javascript" src="https://aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.js" charset="utf-8">< /script>
 *
 *      Google Charts needs the following script to be loaded:
 *      <script type="text/javascript" src="https://www.gstatic.com/charts/loader.js">< /script>
 * 
 * Example:
 * 
 *  AstroMosaicEngine("horsehead nebula", params, "target-div", "day-div", "year-div");
 */
function AstroMosaicEngine(target, params, target_div, day_div, year_div, radec_div)
{
    console.log('AstroMosaicEngine');

    var engine_params = {
        fov_x : params.fov_x,
        fov_y : params.fov_y,
        am_fov_x : getAstroMosaicFov(params.fov_x),
        am_fov_y : getAstroMosaicFov(params.fov_y),
        location_lat : params.location_lat,
        location_lng : params.location_lng,
        horizonSoft : params.horizonSoft,
        horizonHard : params.horizonHard,
        meridian_transit : params.meridian_transit,
        UTCdate_ms : params.UTCdate_ms,
        timezoneOffset : params.timezoneOffset,
        grid_type : params.grid_type ? params.grid_type : "fov",
        grid_size_x : params.grid_size_x ? params.grid_size_x : 1,
        grid_size_y : params.grid_size_y ? params.grid_size_y : 1,
        isCustomMode : params.isCustomMode,
        chartTextColor : params.chartTextColor,
        gridlinesColor : params.gridlinesColor,
        backgroundColor : params.backgroundColor,
        isRepositionModeFunc : null,
        repositionTargetFunc : null,
        showAz: false,
        planet_id: null,
        current_telescope_service: null
    };

    var engine_panels = {
        aladin_panel : target_div,
        aladin_panel_text : radec_div ? radec_div : null,
        dayvisibility_panel : day_div,
        dayvisibility_panel_text : null,
        yearvisibility_panel : year_div,
        yearvisibility_panel_text : null,
        status_text : null,
        error_text : null,
        panel_view_x : null,
        panel_view_y : null,
        panel_view_div : null,
        panel_view_text : null
    };

    if (engine_params.horizonSoft != null && engine_params.horizonHard == null) {
        // we have only soft horizon, use it as hard horizon
        console.log('AstroMosaicEngine, use soft horizon as hard horizon');
        engine_params.horizonHard = engine_params.horizonSoft;
        engine_params.horizonSoft = null;
    }
    if (engine_params.horizonSoft != null) {
        engine_params.horizonSoft = fillHorizonLimits(engine_params.horizonSoft);
    }
    engine_params.horizonHard = fillHorizonLimits(engine_params.horizonHard);

    if (engine_params.UTCdate_ms == null) {
        // Use current date
        var d = new Date();
        var year = d.getUTCFullYear();
        var month = d.getUTCMonth();
        var day = d.getUTCDate();
        engine_params.UTCdate_ms = Date.UTC(year, month, day, 0, 0, 0, 0);
    }
    var curdate = new Date();
    engine_params.UTCdate_now_ms = Date.UTC(curdate.getUTCFullYear(), curdate.getUTCMonth(), curdate.getUTCDate(), 
                                            curdate.getUTCHours(), curdate.getUTCMinutes());

    return StartAstroMosaicViewerEngine(
                "embedded", 
                target, 
                engine_params, 
                engine_panels, 
                null, 
                params.grid_overlap ? params.grid_overlap : 20);
}

/* 
 * Utility routine to convert FoV degrees to format used by StartAstroMosaicViewerEngine.
 */
function getAstroMosaicFov(fov)
{
    return (fov*60.0)/3600.0;
}

/* 
 * Ensure that we have horizon limits fov every 5 arcminutes.
 */
function fillHorizonLimits(horizon_limits)
{
    if (horizon_limits == null || horizon_limits.length == 0) {
        horizon_limits = [0];
    }
    var len = horizon_limits.length;
    if (len < 71) {
        // we need limit for every 5 arcminutes
        var last = horizon_limits[len-1];
        for (var k = len; k < 71; k++) {
            horizon_limits[k] = last;
        }
    }
    return horizon_limits;
}

function filterImageTargetList(image_target_list)
{
    var new_image_target_list = [];
    var marker_list = [];
    for (var i = 0; i < image_target_list.length; i++) {
        var s = image_target_list[i].trim();
        if (s.startsWith("marker")) {
            console.log("filterImageTargetList ", s);
            s = s.substring(6).trim();
            console.log("filterImageTargetList removed marker", s);
            marker_list.push(s);
        } else {
            new_image_target_list.push(s);
        }
    }
    return { image_target_list: new_image_target_list, marker_list: marker_list };
}

// orbital elements of planets
var planets = [
    {
        name: "Mercury",
        N: [ 48.3313, 0.0000324587 ],
        i: [ 7.0047, 0.00000005 ],
        w: [ 29.1241, 0.0000101444 ],
        a: [ 0.387098, 0 ],
        e: [ 0.205635, -0.000000000559 ],
        M: [ 168.6562, 4.0923344368 ]
    },
    {
        name: "Venus",
        N: [ 76.6799, 0.0000246590 ],
        i: [ 3.3946, 0.0000000275 ],
        w: [ 54.8910, 0.0000138374 ],
        a: [ 0.723330, 0 ],
        e: [ 0.006773, 0.000000001302 ],
        M: [ 48.0052, 1.6021302244 ]
    },
    {
        name: "Mars",
        N: [ 49.5574, 0.0000211081 ],
        i: [ 1.8497, -0.0000000178 ],
        w: [ 286.5016, 0.0000292961 ],
        a: [ 1.523688, 0 ],
        e: [ 0.093405, 0.000000002516 ],
        M: [ 18.6021, 0.5240207766 ]
    },
    {
        name: "Jupiter",
        N: [ 100.4542, 0.000026854 ],
        i: [ 1.3030, -0.0000001557 ],
        w: [ 273.8777, 0.0000164505 ],
        a: [ 5.20256, 0 ],
        e: [ 0.048498, 0.000000004469 ],
        M: [ 19.8950, 0.0830853001 ]
    },
    {
        name: "Saturn",
        N: [ 113.6634, 0.0000238980 ],
        i: [ 2.4886, -0.0000001081 ],
        w: [ 339.3939, 0.0000297661 ],
        a: [ 9.55475, 0 ],
        e: [ 0.055546, -0.000000009499 ],
        M: [ 316.9670, 0.0334442282 ]
    },
    {
        name: "Uranus",
        N: [ 74.0005, 0.000013978 ],
        i: [ 0.7733, 0.000000019 ],
        w: [ 96.6612, 0.000030565 ],
        a: [ 19.18171, -0.0000000155 ],
        e: [ 0.047318, 0.00000000745 ],
        M: [ 142.5905, 0.011725806 ]
    },
    {
        name: "Neptune",
        N: [ 131.7806, 0.000030173 ],
        i: [ 1.7700, -0.000000255 ],
        w: [ 272.8461, -0.000006027 ],
        a: [ 30.05826, 0.00000003313 ],
        e: [ 0.008606, 0.00000000215 ],
        M: [ 260.2471, 0.005995147 ]
    }
];

/*************************************************************************
 *
 *      StartAstroMosaicViewerEngine
 * 
 * Interface for the native viewer.
 *
 * Parameters:
 *
 *      img_fov - field of view for single image considering the overlap
 */
function StartAstroMosaicViewerEngine(
    engine_view_type, 
    target, 
    engine_params, 
    engine_panels, 
    engine_catalogs, 
    img_fov,
    engine_native_resources,
    json_target)
{
    var resolved_name = null;
    var resolved_coordinates = null;

    var target_ra;
    var target_dec;

    var hour_ms = 60*60*1000;
    var day_ms = 24*hour_ms;
    var degToRad = Math.PI/180.0;
    var radToDeg = 180.0/Math.PI;
    var degToHours = 1/15;
    var hoursToDeg = 15;
    var JD1970 = 2440587.5;     // JD 1970-01-01 00:00 - Javascript zero time

    var engine_data = {
        aladin : null,
        aladinarr : [],
        daydata : null,
        daychart : null,
        yeardata : null,
        yearchart : null

    };
    var aladin_fov;
    var aladin_fov_extra = 1;
    var aladin_position = null;
    var aladin_view_ready = false;

    var image_target;
    var image_target_list = [];
    var marker_list = [];

    var engine_error_text = null;

    var catalogSimbad = null;
    var catalogNED = null;

    console.log('StartAstroMosaicViewerEngine', engine_view_type, target);

    if (engine_view_type == 'get_engine_native_resources') {
        engine_native_resources.sun_rise_set = sun_rise_set;
        engine_native_resources.object_altitude_init = object_altitude_init;
        engine_native_resources.object_altaz = object_altaz;
        engine_native_resources.object_altitude_get = object_altitude_get;
        engine_native_resources.moon_position = moon_position;
        engine_native_resources.moon_topocentric_correction = moon_topocentric_correction;
        engine_native_resources.moon_distance = moon_distance;
        engine_native_resources.getTargetAboveRightNow = getTargetAboveRightNow;
        return;
    }

    if (!engine_params.timezoneOffset) {
        engine_params.timezoneOffset = 0;
    }

    console.log('timezoneOffset', engine_params.timezoneOffset);

    var grid_type = engine_params.grid_type;

    image_target = target.trim();
    image_target_list = [];
    img_fov = 1 - img_fov / 100;

    var c = image_target.substr(0,1);
    var c2 = image_target.substr(0,2);
    console.log('StartAstroMosaicViewerEngine', 'c', c, 'c2', c2);
    if (json_target) {
        EngineViewTargetPanels(json_target);
    } else if (c == '{') {
        console.log('StartAstroMosaicViewerEngine: json target ', image_target);
        EngineViewTargetPanels(JSON.parse(image_target));
    } else if (json_target) {
        EngineViewTargetPanels(json_target);
    } else if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c2 == 'd ') {
        console.log('image_target is number');
        image_target_list = image_target.split(',');
        let obj = filterImageTargetList(image_target_list);
        image_target_list = obj.image_target_list;
        marker_list = obj.marker_list;
        for (var i = 0; i < image_target_list.length; i++) {
            image_target_list[i] = reformat_coordinates(image_target_list[i]);
        }
        console.log('image_target_list', image_target_list);
        for (var i = 0; i < marker_list.length; i++) {
            marker_list[i] = reformat_coordinates(marker_list[i]);
        }
        console.log('marker_list', marker_list);
        image_target = image_target_list[0];
        EngineViewImageByType();
    } else {
        console.log('image_target is name');
        // try to resolve target as a name
        EngineViewImageByName();
    }
    return engine_data;

    function build_error_text(txt)
    {
        return "<strong>" + txt + "</strong>";
    }

    function degrees_to_radians(degrees)
    {
        var pi = Math.PI;
        return degrees * (pi/180);
    }

    // convert image_target HH:MM:SS DEG:HH:MM to decimal degrees
    function get_ra_dec(target)
    {
        var radec = [];

        // assume format HH:MM:SS DEG:HH:MM
        var radec = target.split(' ');
        
        var raparts = radec[0].split(':');
        var decparts = radec[1].split(':');

        radec[0] = Math.abs(parseFloat(raparts[0])) + (parseFloat(raparts[1]) * 60 + parseFloat(raparts[2])) / 3600;
        if (isNaN(radec[0])) {
            // assume seconds are missing
            radec[0] = Math.abs(parseFloat(raparts[0])) + (parseFloat(raparts[1]) * 60) / 3600;
        }
        if (isNaN(radec[0])) {
            // assume minutes are missing
            radec[0] = Math.abs(parseFloat(raparts[0]));
        }
        if (isNaN(radec[0])) {
            return [];
        }
        // convert from hours to degrees
        radec[0] = radec[0] * hoursToDeg;
        if (parseFloat(raparts[0]) < 0) {
            radec[0] = -radec[0];
        }
        radec[1] = Math.abs(parseFloat(decparts[0])) + (parseFloat(decparts[1]) * 60 + parseFloat(decparts[2])) / 3600;
        if (isNaN(radec[1])) {
            // assume seconds are missing
            radec[1] = Math.abs(parseFloat(decparts[0])) + (parseFloat(decparts[1]) * 60) / 3600;
        }
        if (isNaN(radec[1])) {
            // assume minutes are missing
            radec[1] = Math.abs(parseFloat(decparts[0]));
        }
        if (isNaN(radec[1])) {
            return [];
        }
        if (parseFloat(decparts[0]) < 0) {
            radec[1] = -radec[1];
        }
        return radec;
    }

    // convert image_target HH:MM:SS DEG:HH:MM to decimal degrees into target_ra and target_dec
    function get_image_target_ra_dec()
    {
        var radec = get_ra_dec(image_target);
        if (radec.length != 2) {
            return false;
        }
        target_ra = radec[0];
        target_dec = radec[1];

        return true;
    }

    // scale degrees to 0-360
    function scale_to_360(v)
    {
        while (v < 0) {
            v = v + 360;
        }
        return v - Math.floor(v/360)*360;
    }

    // sin from decimal degrees
    function sind(deg)
    {
        return Math.sin(deg*degToRad);
    }

    // cos from decimal degrees
    function cosd(deg)
    {
        return Math.cos(deg*degToRad);
    }

    // Julian Days from 2000, including fraction, used by sun and moon calculations
    function getJD(d)
    {
        var days = JD1970 + d / day_ms - 2451543.5;
        return days;
    }

    // Days from J2000, including fraction, used by altitude calculations
    function getJ2000_2(d)
    {
        var days = JD1970 + d / day_ms - 2451545.0;
        return days;
    }

    function getLocalSiderealTime(lng, date)
    {
        // universal time in decimal hours
        var H = (date % day_ms) / hour_ms;

        // Julian date including fraction - 2451545.0,
        // that is days from J2000
        var D = getJ2000_2(date);

        // calculate local sidereal time in degrees
        var LST = 100.4606184 + 0.9856473662862 * D + H * hoursToDeg + lng;

        // get hours
        LST = LST % 360;

        return LST;
    }

    function getTargetAboveRightNow(lat, lng, date)
    {
        // Ra is the same as the local sidereal time
        // Calculate local sidereal time in degrees
        var ra = getLocalSiderealTime(lng, date);
        if (ra > 180) {
            ra = 360 - ra;
        }

        ra = ra * degToHours;

        // Dec is the same as latitude
        var dec = lat;

        return [ra, dec];
    }

    // Calculate object altitude. 
    // Useful links:
    //      https://astronomy.stackexchange.com/questions/24859/local-sidereal-time
    //      https://observability.date/notes
    //      http://njsas.org/projects/tidal_forces/altaz/pausch/riset.html
    //      http://www.stjarnhimlen.se/comp/tutorial.html
    //      http://www.stargazing.net/kepler/altaz.html
    function object_altaz(date, ra, dec, lat, lng)
    {
        // calculate local sidereal time in degrees
        var LST = getLocalSiderealTime(lng, date);

        // calculate local hour angle in degrees
        var LHA = LST - ra;

        // calculate sin(altitude) in radian
        var sin_altitude = sind(lat) * sind(dec) + cosd(lat) * cosd(dec) * cosd(LHA);

        var altitude = Math.asin(sin_altitude) * radToDeg;

        // calculate AZ
        var cos_A = (sind(dec) - sind(altitude)*sind(lat)) / (cosd(altitude)*cosd(lat));

        var A = Math.acos(cos_A) * radToDeg;

        var AZ;
        if (sind(LHA) < 0) {
            AZ = A;
        } else {
            AZ = 360 - A;
        }

        //console.log("object_altaz, last=",LST*degToHours,",lha=",LHA*degToHours,",sinalt=",sin_altitude,",alt=",altitude,",H=",H);

        return {alt:altitude, az:AZ};
    }

    // Do calculations that are not based on RA/DEC
    function object_altitude_init(date, lat, lng)
    {
        // calculate local sidereal time in degrees
        var LST = getLocalSiderealTime(lng, date);

        var aa =  {Lst: LST, Sinlat: sind(lat), Coslat: cosd(lat)}

        console.log("object_altitude_init, aa", aa);

        return aa;
    }

    // Calculate altitude on given RA/DEC
    function object_altitude_get(aa, ra, dec)
    {
        // calculate local hour angle in degrees
        var LHA = aa.Lst - ra;

        // calculate sin(altitude) in radian
        var sin_altitude = aa.Sinlat * sind(dec) + aa.Coslat * cosd(dec) * cosd(LHA);

        var altitude = Math.asin(sin_altitude) * radToDeg;

        return altitude;
    }

    function planet_position(date, planet)
    {
        // Days from J2000
        var d = getJD(date);
        var pi = Math.PI;
        var nloop;
        //console.log("planet position d=",d,"JD=",JD1970+d/day_ms);

        var N = scale_to_360(planet.N[0] + planet.N[1] * d);
        var i = scale_to_360(planet.i[0] + planet.i[1] * d);
        var w = scale_to_360(planet.w[0] + planet.w[1] * d);
        var a = scale_to_360(planet.a[0] + planet.a[1] * d);
        var e = scale_to_360(planet.e[0] + planet.e[1] * d);
        var M = scale_to_360(planet.M[0] + planet.M[1] * d);
        //console.log("N",N,"i",i,"w",w,"a",a,"e",e,"M",M);

        var E = M + e*(180/pi) * sind(M) * ( 1.0 + e * cosd(M) );
        for (nloop = 0; nloop < 100; nloop++) {
            var E0 = E;
            E = E0 - (E0 - e * (180/pi) * sind(E0) - M) / (1- e * cosd(E0));
            if (Math.abs(E-E0) <= 0.001) {
                break;
            }
        }
        //console.log("E", E, "nloop", nloop);

        var x = a * ( cosd(E) - e );
        var y = a * Math.sqrt(1.0 - e*e) * sind(E);
        //console.log("x,y",x,y);

        var r = Math.sqrt( x*x + y*y );
        var v = scale_to_360(Math.atan2( y, x ) * radToDeg);
        //console.log("r,v",r,v);

        // planet heliocentric position in ecliptic rectangular coordinates
        var xeclip = r * ( cosd(N) * cosd(v+w) - sind(N) * sind(v+w) * cosd(i) );
        var yeclip = r * ( sind(N) * cosd(v+w) + cosd(N) * sind(v+w) * cosd(i) );
        var zeclip = r * ( sind(v+w) * sind(i) );
        //console.log("planet heliocentric xeclip=",xeclip,",yeclip=",yeclip,",zeclip=",zeclip);

        var sunpos = sun_position(date);

        // convert the planets' heliocentric positions to geocentric positions
        xeclip += sunpos.xeclip;
        yeclip += sunpos.yeclip;
        zeclip += sunpos.zeclip;
        //console.log("planet geocentricx eclip=",xeclip,",yeclip=",yeclip,",zeclip=",zeclip);

        var oblecl = 23.4;

        // rotate ecliptic coordinates to equatorial coordinates
        var xequat = xeclip;
        var yequat = yeclip * cosd(oblecl) - zeclip * sind(oblecl);
        var zequat = yeclip * sind(oblecl) + zeclip * cosd(oblecl);
        //console.log("planet xequat=",xequat,",yequat=",yequat,",zequat=",zequat);

        // calculate RA and Dec
        var RA  = scale_to_360(Math.atan2( yequat, xequat ) * radToDeg);
        var Dec = Math.atan2( zequat, Math.sqrt(xequat*xequat+yequat*yequat) ) * radToDeg;

        //console.log("planet ra",RA,",dec",Dec);
        return {ra:RA, dec:Dec};
    }

    // Simplified version of moon position at given time.
    // - there are a lot of variables that affect correct moon position that
    //    are ignored here
    // - we do not correct for altitude
    // Links:
    //      http://www.stjarnhimlen.se/comp/tutorial.html
    function moon_position(date)
    {
        // Days from J2000
        var d = getJD(date);
        var pi = Math.PI;
        var nloop;
        //console.log("moon position d=",d,"JD=",JD1970+d/day_ms);

        var N = scale_to_360(125.1228 - 0.0529538083 * d);
        var i = 5.1454;
        var w = scale_to_360(318.0634 + 0.1643573223 * d);
        var a = 60.2666;
        var e = 0.054900;
        var M = scale_to_360(115.3654 + 13.0649929509 * d);
        //console.log("N",N,"i",i,"w",w,"a",a,"e",e,"M",M);

        var E = M + e*(180/pi) * sind(M) * ( 1.0 + e * cosd(M) );
        for (nloop = 0; nloop < 100; nloop++) {
            var E0 = E;
            E = E0 - (E0 - e * (180/pi) * sind(E0) - M) / (1- e * cosd(E0));
            if (Math.abs(E-E0) <= 0.001) {
                break;
            }
        }
        //console.log("E", E, "nloop", nloop);

        var x = a * ( cosd(E) - e );
        var y = a * Math.sqrt(1.0 - e*e) * sind(E);
        //console.log("x,y",x,y);

        var r = Math.sqrt( x*x + y*y );
        var v = scale_to_360(Math.atan2( y, x ) * radToDeg);
        //console.log("r,v",r,v);

        // moon geocentric position in ecliptic coordinates
        var xeclip = r * ( cosd(N) * cosd(v+w) - sind(N) * sind(v+w) * cosd(i) );
        var yeclip = r * ( sind(N) * cosd(v+w) + cosd(N) * sind(v+w) * cosd(i) );
        var zeclip = r * ( sind(v+w) * sind(i) );
        //console.log("moon xeclip=",xeclip,",yeclip=",yeclip,",zeclip=",zeclip);

        // ecliptic longitude and latitude
        //var lonecl = scale_to_360(Math.atan2( yeclip, xeclip ) * radToDeg);
        //var latecl = Math.atan2( zeclip, Math.sqrt(xeclip*xeclip+yeclip*yeclip) ) * radToDeg;
        //console.log("lonecl,latecl",lonecl,latecl);

        var oblecl = 23.4;

        // rotate ecliptic coordinates to equatorial coordinates
        var xequat = xeclip;
        var yequat = yeclip * cosd(oblecl) - zeclip * sind(oblecl);
        var zequat = yeclip * sind(oblecl) + zeclip * cosd(oblecl);
        //console.log("moon xequat=",xequat,",yequat=",yequat,",zequat=",zequat);

        // calculate RA and Dec
        var RA  = scale_to_360(Math.atan2( yequat, xequat ) * radToDeg);
        var Dec = Math.atan2( zequat, Math.sqrt(xequat*xequat+yequat*yequat) ) * radToDeg;

        //console.log("moon ra",RA,",dec",Dec);

        return {ra:RA, dec:Dec};
    }

    // a simple version for topocentric correction
    function moon_topocentric_correction(alt)
    {
        var r = 60.336;
        return alt - Math.asin(1/r) * cosd(alt);
    }

    // Sun position at given time.
    // Links:
    //      http://www.stjarnhimlen.se/comp/tutorial.html
    function sun_position(date)
    {
        // Days from J2000
        var d = getJD(date);
        var pi = Math.PI;
        //console.log("sun_position d", d);

        var w = scale_to_360(282.9404 + 4.70935E-5 * d);
        var a = 1.0;
        var e = 0.016709 - 1.151E-9 * d;
        var M = scale_to_360(356.0470 + 0.9856002585 * d);

        //console.log(w,a,e,M);

        var oblecl = scale_to_360(23.4393 - 3.563E-7 * d);
        var L = scale_to_360(w + M);
        //console.log("L", L,"oblecl", oblecl);

        var E = scale_to_360((M + (180/pi) * e * sind(M) * (1 + e * cosd(M))));
        //console.log("E", E);

        // Sun's rectangular coordinates
        var x = cosd(E) - e;
        var y = sind(E) * Math.sqrt(1 - e*e);
        //console.log("x,y", x,y);

        var r = Math.sqrt(x*x + y*y);
        var v = Math.atan2( y, x ) * radToDeg;
        //console.log("r,v", r,v);

        var lon = scale_to_360(v + w);
        //console.log("lon", lon);

        // Sun's ecliptic rectangular coordinates
        x = r * cosd(lon);
        y = r * sind(lon);
        //console.log("sun x,y", x,y);

        var xequat = x;
        var yequat = y * cosd(oblecl);
        var zequat = y * sind(oblecl);
        //console.log("sun xequat,yequat", xequat,yequat);

        var RA  = Math.atan2( yequat, xequat ) * radToDeg;
        var Dec = Math.atan2( zequat, Math.sqrt(xequat*xequat+yequat*yequat) ) * radToDeg;

        //console.log("Sun_position", RA, Dec);

        return {ra:RA, dec:Dec, xeclip: x, yeclip: y, zeclip: 0.0};
    }

    // Simplified version of rise and set times.
    // - we do not correct for altitude
    // - we use current day rise time as next day rise time
    // - h is altitude in degrees from horizon
    //   0      center of sun's disk on horizon
    //   -12    nautical twilight
    //   -15    Amateur astronomical twilight
    //   -18    Astronomical twilight
    // Links:
    //      http://www.stjarnhimlen.se/comp/tutorial.html
    function sun_rise_set(midday, lat, lon, h)
    {
        var d = getJD(midday);
        
        var sun_pos = sun_position(midday);
        var LST = sun_pos.ra;

        var w = scale_to_360(282.9404 + 4.70935E-5 * d);
        var M = scale_to_360(356.0470 + 0.9856002585 * d);
        var L = M + w;
        var GMST0 = scale_to_360(L + 180);

        var UT_sun = (LST - GMST0 - lon) * degToHours;
        if (UT_sun < 0) {
            UT_sun = UT_sun + 24;
        }
        //console.log("Sun_rise_set UT_sun", UT_sun);

        // calculate midday at location
        midday = midday - 12 * hour_ms + UT_sun * hour_ms;

        var cos_LHA = (sind(h) - sind(lat)*sind(sun_pos.dec)) / (cosd(lat) * cosd(sun_pos.dec));

        var LHA = (Math.acos(cos_LHA) * radToDeg) * degToHours;
        //console.log("Sun_rise_set LHA", LHA);

        //console.log("Sun_rise_set set rise", 12+LHA, 12-LHA);

        // we use the current day sunrise as the next sunrise which is not exactly correct
        return {sunset: midday + LHA*hour_ms, sunrise: midday - LHA*hour_ms + day_ms};
    }

    // Calculate distance in degrees between two (ra,dec) positions
    function moon_distance(ra1, dec1, ra2, dec2)
    {
        var cos_A = sind(dec1) * sind(dec2) + cosd(dec1) * cosd(dec2) * cosd(ra1 - ra2);
        var A = Math.acos(cos_A) * radToDeg;
        if (A < 0) {
            A = -A;
        }
        if (A > 180) {
            A = 360 - A;
        }
        return A;
    }

    // This method can be found in many places, somehow
    // it gives weird results
    function get_moon_phase2(date)
    {
        var d = getJD(date);

        var v = (d-2451550.1) / 29.530588853;
        v = v - Math.floor(v);
        if (v < 0) {
            v = v + 1;
        }

        var age = v * 29.53;
        return age;
    }

    // My own version, calculate sun-moon angle to get
    // approximate "phase" in percentages
    function get_moon_phase(d)
    {
        var sunpos = sun_position(d);
        var moonpos = moon_position(d);
        var dist = moon_distance(sunpos.ra, sunpos.dec, moonpos.ra, moonpos.dec);
        //console.log("get_moon_phase dist", dist);
        return (scale_to_360(dist) / 180) * 100;
    }

    // Convert to date string to that e.g. 1:0 becomes 01:00
    function toDateString(num)
    {
        if (num < 10) {
            return '0' + num.toString();
        } else {
            return num.toString();
        }
    }

    function setChartOptions(title, hAxisTitle, seriesStyle, hAxisFormat, showAz)
    {
        var chartTextStyle = {};
        var gridlinesStyle = {};

        if (engine_params.isCustomMode) {
            console.log("setChartOptions, custom mode");
            chartTextStyle = { color: engine_params.chartTextColor };
            gridlinesStyle = { color: engine_params.gridlinesColor };
        } else {
            console.log("setChartOptions, default mode");
        }

        var options = {
            title: title,
            legendTextStyle: chartTextStyle,
            titleTextStyle: chartTextStyle,
            hAxis: { 
                title: hAxisTitle,
                textStyle: chartTextStyle,
                titleTextStyle: chartTextStyle,
                gridlines: gridlinesStyle,
                format: hAxisFormat
            },
            legend:{
                textStyle: chartTextStyle
            },
            // minorGridlines: { units: { hours: {format: ['HH:MM']} } },
            series: seriesStyle
        };

        var vAxisAlt = { 
            title: 'Altitude (degrees)',
            textStyle: chartTextStyle,
            titleTextStyle: chartTextStyle,
            gridlines: gridlinesStyle
        };

        if (showAz) {
            options.vAxes = [
                vAxisAlt,
                { 
                    title: 'Azimuth',
                    textStyle: chartTextStyle,
                    titleTextStyle: chartTextStyle,
                    gridlines: gridlinesStyle,
                }
            ];
        } else {
            options.vAxis = vAxisAlt;
        }

        if (engine_params.isCustomMode) {
            options.backgroundColor = engine_params.backgroundColor;
        }
        return options;
    }

    function dayVisibilityTime(celldate)
    {
        return toDateString(celldate.getUTCHours()) + ":" + toDateString(celldate.getUTCMinutes());
    }

    function drawDayVisibilityandGrid() 
    {
        console.log("drawDayVisibilityandGrid, image_target_list.length", image_target_list.length);

        if (engine_view_type == "all"
            || ((engine_view_type == "" || engine_view_type == "embedded") && engine_panels.aladin_panel != null)) 
        {
            if (image_target_list.length > 1) {
                EngineViewGridFromList(image_target_list);
            } else if (engine_params.hasOwnProperty('offaxis')) {
                EngineViewGridOffaxis(image_target_list);
            } else {
                EngineViewGrid(false);
            }
        }
        engine_data.daydata = new google.visualization.DataTable();
        // get midday in UTC time
        var midday = engine_params.UTCdate_ms + day_ms/2;

        // For time column string seem to be better than time because
        // Google charts scales the chart with time and does not show
        // the whole night always. We loose vertical grid lines but
        // to me it looks better to see the whole night and not only
        // a part of it.
        engine_data.daydata.addColumn('string', 'Time');
        engine_data.daydata.addColumn('number', 'Visible');            // object altitude
        if (engine_params.horizonSoft != null) {
            engine_data.daydata.addColumn('number', 'Below soft horizon'); // object altitude if below soft horizon
        }
        engine_data.daydata.addColumn('number', 'Not visible');        // object altitude below hard horizon or meridian transit
        engine_data.daydata.addColumn('number', 'Moon alt');           // moon altitude
        if (engine_params.planet_id != null) {
            engine_data.daydata.addColumn('number', planets[engine_params.planet_id].name);         // planet altitude
        }
        if (engine_params.showAz) {
            engine_data.daydata.addColumn('number', 'Az');             // object azimuth
        }

        var interval = 5*60*1000; // 5 minutes
        
        var ra = target_ra;
        var dec = target_dec;
        
        var lat = engine_params.location_lat;
        var lng = engine_params.location_lng;

        console.log(ra, dec, lat, lng);

        var rowdata = [];

        var draw_full_day = 0;  // if 0 draw only during astronomical twilight

        if (grid_type == "visual") {
            var suntimes = sun_rise_set(midday, lat, lng, 0);
        } else {
            // sun rise and set times that closely match dome open times
            var suntimes = sun_rise_set(midday, lat, lng, -12);
        }

        var starttime;
        var endtime;
        if (draw_full_day) {
            starttime = midday - engine_params.timezoneOffset * 3600 * 1000;
            endtime = starttime + day_ms;
        } else {
            if (engine_params.UTCdatetime_ms != null && engine_params.UTCdatetime_ms < suntimes.sunset) {
                starttime = engine_params.UTCdatetime_ms;
            } else {
                starttime = suntimes.sunset - suntimes.sunset % interval;
            }
            endtime = suntimes.sunrise + interval - suntimes.sunrise % interval;
        }
        var prevaz = null;
        var meridian_index = null;
        var localdate = new Date();

        for (var d = starttime; d <= endtime; d = d + interval) {
            //console.log("d",d,"sunrise",suntimes.sunrise,"unset",suntimes.sunset);
            var altaz = object_altaz(d, ra, dec, lat, lng);
            //console.log("target az=",altaz.az,",alt=",altaz.alt);
            var objectalt = altaz.alt;
            var objectaz = altaz.az;

            var moonpos = moon_position(d);
            var moonalt = object_altaz(d, moonpos.ra, moonpos.dec, lat, lng).alt;
            moonalt = moon_topocentric_correction(moonalt);

            if (engine_params.planet_id != null) {
                var planetpos = planet_position(d, planets[engine_params.planet_id]);
                var planetalt = object_altaz(d, planetpos.ra, planetpos.dec, lat, lng).alt;
                if (planetalt < 0) {
                    planetalt = null;
                }
            }
            var visiblealt = null;     // target visible
            var softalt = null;        // target below soft horizon
            var hardalt = null;        // target below hard horizon or meridian transit

            var horizon_index = Math.round(altaz.az / 5);

            if (prevaz != null) {
                if ((prevaz > 180 && altaz.az < 180) || // from 360 to 0
                    (prevaz < 180 && altaz.az > 180))   // passed 180
                {
                    // save meridian crossing
                    meridian_index = rowdata.length;
                    console.log("meridian_index",meridian_index);
                }
            }
            prevaz = altaz.az;
            if (objectalt > 0) {
                //console.log("objectalt",objectalt,"horizon_index",horizon_index);
                //console.log("soft",horizonSoft[horizon_index],"hard",horizonHard[horizon_index]);
                if (engine_params.horizonSoft != null) {
                    //console.log("drawDayVisibilityandGrid, use both soft and hard horizon");
                    if (objectalt > engine_params.horizonSoft[horizon_index]) {
                        visiblealt = objectalt;
                    } else if (objectalt > engine_params.horizonHard[horizon_index]) {
                        softalt = objectalt;
                    } else {
                        hardalt = objectalt;
                    }
                } else {
                    //console.log("drawDayVisibilityandGrid, only hard horizon");
                    if (objectalt > engine_params.horizonHard[horizon_index]) {
                        visiblealt = objectalt;
                    } else {
                        hardalt = objectalt;
                    }
                }
            }
            if (moonalt < 0) {
                moonalt = null;
            }
            var celldate = new Date(d + engine_params.timezoneOffset*60*60*1000);
            var row = [
                dayVisibilityTime(celldate),
                getAltitudeCellObject(visiblealt) 
            ];
            if (engine_params.horizonSoft != null) {
                row.push(getAltitudeCellObject(softalt));
            }
            row.push(getAltitudeCellObject(hardalt));
            row.push(getAltitudeCellObject(moonalt));
            if (engine_params.planet_id != null) {
                row.push(getAltitudeCellObject(planetalt));
            }
            if (engine_params.showAz) {
                row.push(getAzimuthCellObject(objectaz));
            }
            rowdata[rowdata.length] = row;
        }

        // All rows added
        // Check meridian crossing

        var meridian_crossing = false;
        if (meridian_index != null && engine_params.meridian_transit > 0) {
            // Add meridian crossing to the chart
            var meridian_crossing_index = rowdata[0].length;
            // Mark Meridian crossing. We use engine_params.meridian_transit time here.
            // Maybe it could be done some other way...
            var timer = Math.round(((engine_params.meridian_transit / 2) * 60 * 1000) / interval);
            var begin = Math.max(meridian_index - timer, 0);
            var end = Math.min(meridian_index + timer, rowdata.length);
            if (engine_params.horizonSoft != null) {
                for (var i = begin; i < end; i++) {
                    if (rowdata[i][1] != null) {        // visiblealt != null
                        rowdata[i][meridian_crossing_index] = rowdata[i][1];
                        rowdata[i][1] = null;           // visible = null
                        meridian_crossing = true;
                    } else if (rowdata[i][2] != null) { // softalt != null
                        rowdata[i][meridian_crossing_index] = rowdata[i][2];
                        rowdata[i][2] = null;           // softalt = null
                        meridian_crossing = true;
                    }
                }
            } else {
                for (var i = begin; i < end; i++) {
                    if (rowdata[i][1] != null) {        // visiblealt != null
                        rowdata[i][meridian_crossing_index] = rowdata[i][1];
                        rowdata[i][1] = null;           // visible = null
                        meridian_crossing = true;
                    }
                }
            }
            if (meridian_crossing) {
                engine_data.daydata.addColumn('number', 'Meridian crossing');  // Meridian crossing
                for (var i = 0; i < rowdata.length; i++) {
                    if (rowdata[i].length <= meridian_crossing_index) {
                        rowdata[i].push(null);
                    }
                }
            }
        }

        engine_data.daydata.addRows(rowdata);

        if (!engine_params.timezoneOffset) {
            var hAxisTitle = 'Time (UTC)';
        } else {
            if (engine_params.timezoneOffset >= 0) {
                var hAxisTitle = 'Time (UTC+' + engine_params.timezoneOffset + ')';
            } else {
                var hAxisTitle = 'Time (UTC-' + Math.abs(engine_params.timezoneOffset) + ')';
            }
        }

        var seriesStyle = [ { color: 'green' } ];
        if (engine_params.horizonSoft != null) {
            seriesStyle.push({ color: 'orange', lineDashStyle: [4, 2] });
        }
        seriesStyle.push({ color: 'red', lineDashStyle: [2, 2] });
        seriesStyle.push({ color: '#1c91c0', lineDashStyle: [4, 1, 2], lineWidth: 1 });     // Moon, Blue
        if (engine_params.planet_id != null) {
            seriesStyle.push({ color: 'Magenta', lineDashStyle: [2, 1, 2], lineWidth: 1 }); // Planet, Magenta
        }
        if (engine_params.showAz) {
            seriesStyle.push({ color: 'gray', lineDashStyle: [2, 2], targetAxisIndex: 1 }); // Azimuth
        }
        if (meridian_crossing) {
            seriesStyle.push({ color: 'green', lineDashStyle: [4, 2], lineWidth: 1 });     // Meridian crossing
        }

        var options = setChartOptions('Target visibility', hAxisTitle, seriesStyle, 'HH:mm', engine_params.showAz);

        engine_data.daychart = new google.visualization.LineChart(document.getElementById(engine_panels.dayvisibility_panel));

        engine_data.daychart.draw(engine_data.daydata, options);

        var midnight = suntimes.sunset + (suntimes.sunrise - suntimes.sunset) / 2;

        // We use sun and moon distance in degrees at midnight to approximate 
        // the moon "phase". I guess there is also a correct way...
        var moon_phase = get_moon_phase(midnight);
        // Moon distance from object at midnight. Distance changes during the night
        // but not much so this should be fine.
        var moonpos_midnight = moon_position(midnight);
        var moon_angle = moon_distance(ra, dec, moonpos_midnight.ra, moonpos_midnight.dec);

        if (engine_view_type == "all") {
            document.getElementById(engine_panels.dayvisibility_panel_text).innerHTML = 
                //"Astronomical twilight start : " + UTCsunset.toUTCString() + "<br>" +
                //"Astronomical twilight end : " + UTCsunrise.toUTCString() + "<br>" +
                "Moon phase: " + Math.floor(moon_phase) + "%<br>" +
                "Moon distance from target: " + Math.floor(moon_angle) + " degrees";
        } else if (engine_panels.dayvisibility_panel_text) {
            document.getElementById(engine_panels.dayvisibility_panel_text).style.marginTop = "1px";
            document.getElementById(engine_panels.dayvisibility_panel_text).innerHTML = engine_params.astro_mosaic_link;
        }
    }

    function getAltitudeCellObject(val)
    {
        if (val == null) {
            return null;
        } else {
            return { v: val, f: val.toFixed(0) + "°" };
        }
    }

    function getAzimuthCellObject(val)
    {
        var diff = 45/2;
        if (val < diff) {
            var dir = "N";
        } else if (val < 90 - diff) {
            var dir = "NE";
        } else if (val < 90 + diff) {
            var dir = "E";
        } else if (val < 180 - diff) {
            var dir = "SE";
        } else if (val < 180 + diff) {
            var dir = "S";
        } else if (val < 270 - diff) {
            var dir = "SW";
        } else if (val < 270 + diff) {
            var dir = "W";
        } else if (val < 360 - diff) {
            var dir = "NW";
        } else {
            var dir = "N";
        }
        if (val == null) {
            return null;
        } else {
            return { v: val, f: val.toFixed(0) + " " + dir};
        }
    }

    function drawYearVisibility() 
    {
        console.log("drawYearVisibility");

        engine_data.yeardata = new google.visualization.DataTable();
        // get midday in UTC time in ms
        var midday = engine_params.UTCdate_ms + day_ms/2;

        engine_data.yeardata.addColumn('date', 'Date');
        engine_data.yeardata.addColumn('number', 'Visible');            // object altitude
        engine_data.yeardata.addColumn('number', 'Not visible');        // moon altitude
        engine_data.yeardata.addColumn('number', 'Moon alt');           // moon altitude
        if (engine_params.planet_id != null) {
            engine_data.yeardata.addColumn('number', planets[engine_params.planet_id].name + ' alt');     // planet altitude
        }

        var interval = day_ms; // day
        
        var ra = target_ra;
        var dec = target_dec;
        
        var lat = engine_params.location_lat;
        var lng = engine_params.location_lng;

        var rowdata = [];

        var starttime = midday;
        var endtime = starttime + 365 * day_ms;

        for (var d = starttime; d <= endtime; d = d + interval) {
            var suntimes = sun_rise_set(d, lat, lng, 0);

            // get approximate midnight
            var midnight = suntimes.sunset + (suntimes.sunrise - suntimes.sunset) / 2;

            var objectalt = object_altaz(midnight, ra, dec, lat, lng).alt;

            var moonpos = moon_position(midnight);
            var moonalt = object_altaz(midnight, moonpos.ra, moonpos.dec, lat, lng).alt;
            moonalt = moon_topocentric_correction(moonalt);

            if (engine_params.planet_id != null) {
                var planetpos = planet_position(midnight, planets[engine_params.planet_id]);
                var planetalt = object_altaz(midnight, planetpos.ra, planetpos.dec, lat, lng).alt;
                if (planetalt < 0) {
                    planetalt = null;
                }
            }

            var visiblealt = null;     // target visible
            var hardalt = null;        // target below 30 degrees

            if (objectalt >= 30) {
                visiblealt = objectalt;
            } else if (objectalt > 0) {
                hardalt = objectalt;
            }
            if (moonalt < 0) {
                moonalt = null;
            }
            var row = [
                        new Date(d),
                        getAltitudeCellObject(visiblealt),
                        getAltitudeCellObject(hardalt),
                        getAltitudeCellObject(moonalt)
                      ];
            if (engine_params.planet_id != null) {
                row[row.length] = getAltitudeCellObject(planetalt);
            }
            rowdata[rowdata.length] = row;
        }

        engine_data.yeardata.addRows(rowdata);

        var seriesStyle = [ { color: 'green' } ];
        seriesStyle.push({ color: 'red', lineDashStyle: [2, 2] });
        seriesStyle.push({ color: '#1c91c0', lineDashStyle: [4, 1, 2], lineWidth: 1 });
        if (engine_params.planet_id != null) {
            seriesStyle.push({ color: 'Magenta', lineDashStyle: [2, 1, 2], lineWidth: 1 });
        }
        var options = setChartOptions(
                        'Target visibility at midnight over next 12 months',
                        'Month',
                        seriesStyle,
                        "MMM YYYY",
                        false);

        engine_data.yearchart = new google.visualization.LineChart(document.getElementById(engine_panels.yearvisibility_panel));

        engine_data.yearchart.draw(engine_data.yeardata, options);

        if (engine_view_type != "all" && engine_panels.yearvisibility_panel_text) {
            document.getElementById(engine_panels.yearvisibility_panel_text).style.marginTop = "1px";
            document.getElementById(engine_panels.yearvisibility_panel_text).innerHTML = engine_params.astro_mosaic_link;
        }
    }

    // update globals when target name is found
    // here we assume target coordinates are in image_target global variable
    function target_name_found()
    {
        resolved_name = image_target;

        // change image_target from name to coordinates
        image_target = trim_spaces(image_target);
        console.log("find_coordinates:image_target=", image_target);
        image_target = reformat_coordinates(image_target);
        //document.getElementById(engine_panels.status_text).innerHTML = "Resolved RA/DEC " + image_target;
        if (engine_view_type == "all") {
            document.getElementById(engine_panels.status_text).innerHTML = "";
        }

        resolved_coordinates = image_target;
    }

    // Find coordinates from Sesame XML output
    // or SIMBAD ascii output
    function find_coordinates(str)
    {
        console.log('find_coordinates');

        var idx = str.indexOf("<jpos>");
        if (idx > 0) {
            console.log('Assume Sesame XML format');
            var coord = str.substr(idx+6, 100);
            console.log("find_coordinates:get coordinates from '", coord, "'");
            var idx2 = coord.indexOf("</jpos>");
            if (idx2 == -1) {
                console.log("find_coordinates:failed to get coordinates from '", coord, "', failed at position ", i.toString());
                return false;
            }
            image_target = coord.substr(0, idx2);
        } else {
            console.log('Simbad ascii output');
            idx = str.indexOf("J2000");
            if (idx == -1) {
                console.log("find_coordinates:could not find 'J2000'");
                return false;
            }
            str = str.substr(idx+4);
            idx = str.indexOf(":");
            if (idx == -1) {
                console.log("find_coordinates:could not find ':'");
                return false;
            }
            var coord = str.substr(idx+1, 100);
            console.log("find_coordinates:get coordinates from '", coord, "'");
            coord = trim_spaces(coord);
            for (var i = 0; i < coord.length; i++) {
                var c = coord.substr(i,1);
                if ((c < '0' || c > '9') && c != '.' && c != '-' && c != '+' && c != ' ') {
                    break;
                }
            }
            if (i < 12) {
                console.log("find_coordinates:failed to get coordinates from '", coord, "', failed at position ", i.toString());
                return false;
            }
            image_target = coord.substr(0, i);
        }

        target_name_found();

        return true;
    }

    // find catalog by name
    function findCatalogName(name)
    {
        var catalog_name = null;
        var target_is_catalog_name = true;
        var is_exact_match = true;
        var retname = name;

        var upname = trim_spaces(name).toUpperCase().replace(/ /g, "");

        if ((upname.substring(0, 1) == 'M' && isNumber(upname.substring(1, 2)))
            || upname.substring(0, 7) == 'MESSIER') 
        {
            catalog_name = 'Messier';
            retname = upname.replace("MESSIER", "M ").replace(/  /g, " ");
            retname = retname.replace("M", "M ").replace(/  /g, " ");
        } else if (upname.substring(0, 3) == 'NGC') {
            retname = upname.replace("NGC", "NGC ").replace(/  /g, " ");
            catalog_name = 'NGC';
        } else if (upname.substring(0, 2) == 'IC') {
            retname = upname.replace("IC", "IC ").replace(/  /g, " ");
            catalog_name = 'IC';
        } else if (upname.substring(0, 3) == 'RCW') {
            retname = upname.replace("RCW", "RCW ").replace(/  /g, " ");
            catalog_name = 'RCW';
        } else if (upname.substring(0, 3) == 'SH2') {
            catalog_name = 'Sharpless';
            retname = upname.replace("SH2", "SH2");
        } else if ((upname.substring(0, 1) == 'G' && isNumber(upname.substring(1, 2))) 
                   || upname.substring(0, 3) == 'GUM') 
        {
            catalog_name = 'RCW';
            retname = upname.replace("GUM", "G ").replace(/ /g, "");
            retname = retname.replace("G", "G ").replace(/ /g, "");
            target_is_catalog_name = false;
            is_exact_match = true;
        } else if ((upname.substring(0, 1) == 'B' && isNumber(upname.substring(1, 2)))
                    || upname.substring(0, 7) == 'Barnard') 
        {
            catalog_name = 'Barnard';
            retname = upname.replace("Barnard", "B ").replace(/  /g, " ");
            retname = retname.replace("B", "B ").replace(/  /g, " ");
        } else if ((upname.substring(0, 3) == 'Ced' && isNumber(upname.substring(3, 4)))
                   || upname.substring(0, 9) == 'Cederblad')
        {
            catalog_name = 'Cederblad';
            retname = upname.replace("Cederblad", "Ced ").replace(/  /g, " ");
            retname = retname.replace("Ced", "Ced ").replace(/  /g, " ");
        } else {
            target_is_catalog_name = false;
            is_exact_match = false;
        }
        if (catalog_name != null) {
            console.log("findCatalogName " + retname + " from " + catalog_name + ", exact_match " + is_exact_match);
        } else {
            console.log("findCatalogName " + retname + " from all catalogs, exact_match " + is_exact_match);
            alert("Unable to find " + retname);
        }
        return { name: retname, catalog_name: catalog_name, target_is_catalog_name: target_is_catalog_name, is_exact_match: is_exact_match};
    }

    function findTargetFromCatalog(targets, name)
    {
        if (targets == null) {
            console.log("findTargetFromCatalog null catalog");
            return null;
        }
        console.log("findTargetFromCatalog name " + name);
        for (var i = 0; i < targets.length; i++) {
            if (targets[i][0].indexOf(name) != -1) {
                return targets[i];
            }
        }
        return null;
    }

    function isNumber(c)
    {
        if (c == null || c == undefined) {
            return false;
        }
        return c >= '0' && c <= '9';
    } 

    function doExactMatch(s, n)
    {
        var i = s.indexOf(n);
        if (i == -1) {
            return false;
        }
        if (isNumber(s[i + n.length])) {
            // another number follows, so we got G11 instead of G1
            return false;
        }
        console.log("doExactMatch found " + n + " from " + s);
        return true;
    }

    function findExactMatch(targets, name)
    {
        if (targets == null) {
            console.log("findExactMatch null catalog");
            return null;
        }
        console.log("findExactMatch name "+ name);
        for (var i = 0; i < targets.length; i++) {
            if (doExactMatch(targets[i][0], name)       // CAT
               || doExactMatch(targets[i][7], name)     // NAME
               || doExactMatch(targets[i][8], name))    // INFO
            {
                return targets[i];
            }
        }
        return null;
    }

    function findFromCatalog(targets, name)
    {
        if (targets == null) {
            console.log("findFromCatalog null catalog");
            return null;
        }
        console.log("findFromCatalog name " + name);
        var re = new RegExp(name, "i");
        for (var i = 0; i < targets.length; i++) {
            if (targets[i][0].search(re) != -1       // CAT
               || targets[i][7].search(re) != -1     // NAME
               || targets[i][8].search(re) != -1)    // INFO
            {
                return targets[i];
            }
        }
        return null;
    }

    // if name resolver fails try to resolve name from loaded catalogs
    function resolveNameFromCatalogs(name)
    {
        console.log("resolveNameFromCatalogs " + name);

        var catinfo = findCatalogName(name);
        var target_info = null;

        for (var i = 0; i < engine_catalogs.length; i++) {
            if (catinfo.catalog_name != null) {
                // we check specific catalog
                if (catinfo.catalog_name != engine_catalogs[i].name) {
                    // not the catalog we want to check
                    console.log("resolveNameFromCatalogs skip catalog " + engine_catalogs[i].name);
                    continue;
                }
            }
            console.log("resolveNameFromCatalogs check catalog " + engine_catalogs[i].name + " for name " + catinfo.name);
            if (catinfo.target_is_catalog_name) {
                target_info = findTargetFromCatalog(engine_catalogs[i].targets, catinfo.name);
            } else if (catinfo.is_exact_match) {
                target_info = findExactMatch(engine_catalogs[i].targets, catinfo.name);
            } else {
                target_info = findFromCatalog(engine_catalogs[i].targets, catinfo.name);
            }
            if (target_info != null) {
                // found
                break;
            }
        }
        if (target_info != null) {
            // found the target
            image_target = target_info[1] + " " + target_info[2];
            console.log("resolveNameFromCatalogs found '" + target_info + "', image_target " + image_target);
            target_name_found();
            return true;
        } else {
            console.log("resolveNameFromCatalogs not found");
            return false;
        }
    }

    // Resolve image coordinates from Sesame database using name
    function EngineViewImageByName()
    {
        console.log('EngineViewImageByName');

        if (resolved_name == image_target && resolved_coordinates != null) {
            // same name already resolved, do not resolve again
            if (engine_panels.status_text) {
                document.getElementById(engine_panels.status_text).innerHTML = "RA/DEC " + resolved_coordinates;
            }
            image_target = resolved_coordinates;
            EngineViewImageByType();
            return;
        }

        // Simbad ascii, some problems when accessing the site
        // var resolver_url = "https://simbad.u-strasbg.fr/simbad/sim-id?output.format=ASCII&Ident=";
        
        // Mirror of Simbad u-strasbg? Worked when u-strasbg failed.
        // var resolver_url = "http://simbad.cfa.harvard.edu/simbad/sim-id?output.format=ASCII&Ident=";

        // Sesame uses Simbad, NED and Vizier for resolving. Best documented interface.
        var resolver_url = "https://cdsweb.u-strasbg.fr/cgi-bin/nph-sesame/-oxp/SNV?";

        resolver_url = resolver_url + image_target.replace(/ /g, "+");

        if (engine_panels.error_text) {
            var waitingTimeout = setTimeout(function() {
                                    document.getElementById(engine_panels.error_text).innerHTML = "Resolving name..."; 
                                }, 1000);
        }

        fetch(resolver_url)
            .then(
                function(response) {
                    if (response.status !== 200) {
                        clearTimeout(waitingTimeout);
                        console.log('Problem accessing Sesame name resolver. Status Code: ' + response.status);
                        if (resolveNameFromCatalogs(image_target)) {
                            EngineViewImageByType();
                        } else {
                            engine_error_text = 'Sesame and local name resolve failed';
                            if (engine_panels.error_text) {
                                document.getElementById(engine_panels.error_text).innerHTML = build_error_text(engine_error_text);
                            }
                            return;
                        }
                    }
                    response.text().then(function(text) {
                        clearTimeout(waitingTimeout);
                        if (find_coordinates(text)) {
                            EngineViewImageByType();
                        } else if (resolveNameFromCatalogs(image_target)) {
                            EngineViewImageByType();
                        } else {
                            engine_error_text = "Failed to resolve name " + image_target;
                            console.log(engine_error_text);
                            if (engine_panels.error_text) {
                                document.getElementById(engine_panels.error_text).innerHTML = build_error_text(engine_error_text);
                            }
                        }
                    })
                }
            )
            .catch(function(err) {
                console.log('Problem accessing Sesame name resolver. Fetch Error :' + err);
                clearTimeout(waitingTimeout);
                if (resolveNameFromCatalogs(image_target)) {
                    EngineViewImageByType();
                } else {
                    engine_error_text = 'Sesame and local name resolve failed';
                    if (engine_panels.error_text) {
                        document.getElementById(engine_panels.error_text).innerHTML = build_error_text(engine_error_text);
                    }
                }
            }
        );
    }

    // Remove leading, trailing and duplicate spaces
    function trim_spaces(str)
    {
        // replace all whitespace to space
        str = str.replace(/\s/g, " ");
        // remove leading and trailing spaces
        str = str.trim();
        for (var i = 0; i < str.length && str.indexOf('  ') != -1; i++) {
            // remove all duplicate spaces
            str = str.replace(/  /g, " ");
        }
        return str;
    }

    function decimal_to_mmss(v, degrees)
    {
        if (degrees) {
            // convert degrees to hours
            //console.log("decimal_to_mmss, degrees, ", v);
            v = '' + parseFloat(v) * degToHours;
            //console.log("decimal_to_mmss, degrees to hours, ", v);
        }
        var sign = '';
        v = v.trim();
        //console.log("decimal_to_mmss, v", v);
        var index = v.indexOf('.');
        if (index == -1) {
            //console.log("decimal_to_mmss, no dot found", v);
            return v;
        }
        var vd = v.substring(index+1);
        //console.log("decimal_to_mmss, vd", vd);
        var d = parseFloat("0."+vd);
        //console.log("decimal_to_mmss, d", d);
        var secs = d * 3600;
        var mins = Math.floor(secs / 60);
        //console.log("decimal_to_mmss, mins", mins);
        secs = secs - mins*60;
        //console.log("decimal_to_mmss, secs", secs);

        var x = v.substring(0, index);
        //console.log("decimal_to_mmss, x", x);
        if (x.charAt(0) == '-') {
            sign = '-';
            x = x.substring(1);
            //console.log("decimal_to_mmss, after sign, x", x);
        }

        var ret = sign + ("0" + x).slice(-2) + ':' + ("0" + mins).slice(-2) + ':' + secs.toFixed(2);
        //console.log("decimal_to_mmss, ret", ret);

        return ret;
    }

    // split [-]XXYYZZ to [-]XX:YY:ZZ
    function split_coord(coord)
    {
            if (coord.length == 7) {
                return coord.substring(0, 1) + split_coord(coord.substring(1));
            } else {
                return coord.substring(0, 2) + ':' +
                    coord.substring(2, 4) + ':' +
                    coord.substring(4); 
            }
    }

    function fix_field_lenght(fld)
    {
        var sign;

        //console.log("fix_field_lenght:in", fld)

        if (fld.charAt(0) == '-') {
            sign = '-';
            fld = fld.substring(1);
        } else {
            sign = '';
        }
        var s = fld.split('.');
        if (s.length > 1) {
            // We have decimals
            fld = sign + ("0" + s[0]).slice(-2) + '.' + (s[1] + "0").slice(0, 2);
        } else {
            fld = sign + ("0" + fld).slice(-2);
        }
        //console.log("fix_field_lenght:out", fld)
        return fld;
    }

    // Ensure that format is HH:MM:SS DD:MM:SS, that is,
    // two numbers on each field.
    function reformat_coordinates_field_lenghts(coord)
    {
        var radec = coord.split(" ");
        for (var i = 0; i < radec.length; i++) {
            var fields = radec[i].split(":");
            for (var j = 0; j < fields.length; j++) {
                fields[j] = fix_field_lenght(fields[j]);
            }
            if (fields.length == 3) {
                radec[i] = fields[0] + ':' + fields[1] + ':' + fields[2];
            } else if (fields.length == 2) {
                var mmsplit = fields[1].split('.');
                if (mmsplit.length == 2) {
                    // we have decimals in minutes
                    radec[i] = fields[0] + ':' + mmsplit[0] + ':' + mmsplit[1];
                } else {
                    radec[i] = fields[0] + ':' + fields[1] + ':00';
                }
                
            }
        }
        return radec[0] + ' ' + radec[1];
    }

    // Reformat coordinates to a format HH:MM:SS DD:MM:SS
    // Input can be: 
    // 1. hour, degrees
    // HH:MM:SS DD:MM:SS, HH MM SS DD MM SS, 
    // HH:MM:SS/DD:MM:SS, HH MM SS/DD MM SS,
    // HHMMSS DDMMSS
    // HH.dec DD.dec
    // 2. degrees
    // d DD.dec DD.dec
    function reformat_coordinates(coord)
    {
        // number, assume coordinates
        coord = trim_spaces(coord);
        if (coord[0] == 'd') {
            var degrees = true;
            coord = trim_spaces(coord.substring(1));
            console.log('reformat_coordinates, we have degrees, =', coord);
        } else {
            var degrees = false;
        }
        //console.log('reformat_coordinates=', coord);
        var numbers = coord.split('/');
        if (numbers.length == 2) {
            coord = trim_spaces(numbers[0] + ' ' + numbers[1]);
            console.log('reformat_coordinates, split by /', coord);
        }
        numbers = coord.split(' ');
        //console.log('reformat_coordinates, numbers.length=', numbers.length);
        if (numbers.length == 2) {
            var ra = numbers[0];
            var dec = numbers[1];
            if (ra.split(':').length == 1) {
                if (ra.indexOf('.') == -1 && dec.indexOf('.') == -1) {
                    //console.log('no dots, assume HHMMSS DDMMSS');
                    coord = split_coord(ra) + ' ' + split_coord(dec);
                    //console.log('reformat_coordinates, length 2, assume HHMMSS DDMMSS', coord);
                } else {
                    //console.log('assume HH.dec DD.dec or DD.dec DD.dec, convert to HH:MM:SS DD:MM:SS');
                    coord = decimal_to_mmss(ra, degrees) + ' ' + decimal_to_mmss(dec, false);
                    //console.log('reformat_coordinates, length 2, assume correct HH.dec DD.dec', coord);
                }
            } else {
                //console.log('reformat_coordinates, length 2 and we have :, assume correct format HH:MM:SS DD:MM:SS', coord);
            }
        } else if (numbers.length == 6) {
            //console.log('separated by space, add colons');
            coord = numbers[0] + ':' + numbers[1] + ':' + numbers[2] + ' ' +
                    numbers[3] + ':' + numbers[4] + ':' + numbers[5];
            //console.log('reformat_coordinates, length "+numbers.length+", use as-is', coord);
        } else if (numbers.length == 5) {
            //console.log('badly formatted SIMBAD case, assume zero last number, separated by space, add colons');
            coord = numbers[0] + ':' + numbers[1] + ':' + numbers[2] + ' ' +
                    numbers[3] + ':' + numbers[4] + ':' + 0;
            //console.log('reformat_coordinates, length "+numbers.length+", use as-is', coord);
        } else {
            //console.log('use as-is');
            //console.log('reformat_coordinates, length 6, reformat', coord);
        }
        coord = reformat_coordinates_field_lenghts(coord);
        //console.log('reformat_coordinates, field lengths fixed', coord);
        return coord;
    }

    function EngineViewImageByType()
    {
        console.log('EngineViewImageByType');
        if (!get_image_target_ra_dec()) {
            engine_error_text = "Failed to parse target RA/DEC";
            console.log(engine_error_text);
            if (engine_panels.error_text) {
                document.getElementById(engine_panels.error_text).innerHTML = build_error_text(engine_error_text);
            }
            return;
        }
        if (engine_view_type == "all" && grid_type == 'panels') {
            EngineViewMosaicPanels();
        } else {
            if (engine_view_type == "target") {
                EngineViewGrid(false);
            } else {
                google.charts.load('current', {'packages':['corechart']});
                if (engine_view_type == "all" 
                    || engine_view_type == "day"
                    || ((engine_view_type == "" || engine_view_type == "embedded") && engine_panels.dayvisibility_panel != null)) 
                {
                    google.charts.setOnLoadCallback(drawDayVisibilityandGrid);
                }
                if (engine_view_type == "all" 
                    || engine_view_type == "year"
                    || ((engine_view_type == "" || engine_view_type == "embedded") && engine_panels.yearvisibility_panel != null)) 
                {
                    google.charts.setOnLoadCallback(drawYearVisibility);
                }
            }
        }
    }

    function getAladinPosition(aladin)
    {
        let radec = aladin.getRaDec();
        let ra_hours = radec[0] * degToHours;
        let dec = radec[1];
        return ra_hours.toFixed(5) + " " + dec.toFixed(5);
    }

    function addSimbadNedAladinCatalogs(aladin, reposition)
    {
        let radec = aladin.getRaDec();
        
        if (catalogSimbad != null) {
            var isShowing = catalogSimbad[0].isShowing;
            console.log("existing catalogSimbad, isShowing = " + isShowing);
            if (!reposition && catalogSimbad[1] != radec[0] && catalogSimbad[2] != radec[1]) {
                console.log("remove simbad catalog");
                catalogSimbad[0].hide();
                catalogSimbad = null;
            }
        } else {
            var isShowing = false;
        }
        if (0 && catalogSimbad == null) {
            // Very slow loading Simbad with Aladin Lite v3
            console.log("add simbad catalog");
            catalogSimbad = [];
            // Limit Simbad and NED catalogs to 1 degree to avoid excessive memory usage
            catalogSimbad[0] = A.catalogFromSimbad({ra: radec[0], dec: radec[1]}, 1);
            catalogSimbad[1] = radec[0];
            catalogSimbad[2] = radec[1];
            if (isShowing) {
                catalogSimbad[0].show();
            } else {
                catalogSimbad[0].hide();
            }
        }
        if (catalogSimbad != null) {
            aladin.addCatalog(catalogSimbad[0]);
        }

        if (catalogNED != null) {
            isShowing = catalogNED[0].isShowing;
            console.log("existing catalogNED, isShowing = " + isShowing);
            if (!reposition && catalogNED[1] != radec[0] && catalogNED[2] != radec[1]) {
                console.log("remove NED catalog");
                catalogNED[0].hide();
                catalogNED = null;
            }
        } else {
            isShowing = false;
        }
        if (0 && catalogNED == null) {
            // Very slow loading NED with Aladin Lite v3
            console.log("add NED catalog")
            catalogNED = [];
            catalogNED[0] = A.catalogFromNED({ra: radec[0], dec: radec[1]}, 1);
            catalogNED[1] = radec[0];
            catalogNED[2] = radec[1];
            if (isShowing) {
                catalogNED[0].show();
            } else {
                catalogNED[0].hide();
            }
        }
        if (catalogNED != null) {
            aladin.addCatalog(catalogNED[0]);
        }
        console.log("addAladinCatalogs, radec = " + radec);
    }

    function addAladinCatalogs(aladin, reposition)
    {
        if (engine_catalogs) {
            for (var i = 0; i < engine_catalogs.length; i++) {
                if (engine_catalogs[i].AladinCatalog != null) {
                    if (!engine_native_resources.skip_slooh_catalog(engine_params.current_telescope_service, engine_catalogs[i])) {
                        aladin.addCatalog(engine_catalogs[i].AladinCatalog);
                    }
                }
            }

            if (marker_list.length > 0) {
                var cat = A.catalog({name: 'Markers', sourceSize: 18});
                aladin.addCatalog(cat);
                for (var i = 0; i < marker_list.length; i++) {
                    let marker_radec = get_ra_dec(marker_list[i]);
                    console.log('Add marker ', marker_radec);
                    cat.addSources(A.source(marker_radec[0], marker_radec[1]));
                }
            }

            addSimbadNedAladinCatalogs(aladin, reposition);
        }
    }

    function EngineInitAladin(aladin_fov, aladin_target)
    {
        console.log('EngineInitAladin', aladin_target, engine_panels.aladin_panel, engine_view_type);
        var aladin = null;
        var layers;
        var fullscreen;
        if (engine_view_type == "all") {
            layers = true;
            fullscreen = true;
        } else {
            layers = false;
            fullscreen = false;
        }
        if (A) {
            document.getElementById(engine_panels.aladin_panel).innerHTML = "";
            aladin = A.aladin('#'+engine_panels.aladin_panel, {survey: "P/DSS2/color", fov:aladin_fov, target:aladin_target,
                            showReticle:false, showZoomControl:false, showFullscreenControl:fullscreen, 
                            showLayersControl:layers, showGotoControl:false, 
                            showControl: false, cooFrame: "J2000", showFrame: false,
                            showSimbadPointerControl: true });
        } else {
            document.getElementById(engine_panels.aladin_panel).innerHTML = "<p>Could not access Aladin Sky Atlas</p>";
        }
        if (aladin) {
            addAladinCatalogs(aladin, false);
        }

        aladin_position = getAladinPosition(aladin);
        console.log('EngineInitAladin', aladin_position);

        // define function triggered when an object is clicked
        if (aladin && engine_view_type == "all") {
            console.log('EngineInitAladin, set objectClicked');
            aladin.on('objectClicked', function(object) {
                if (object) {
                    console.log('aladin objectClicked, show object');
                    object.select();
                    engine_native_resources.aladin_object_clicked(object.data);
                } else {
                    console.log('aladin objectClicked, no object');
                }
            });
            aladin.on('objectHovered', function(object) {
                if (object && object.data) {
                    engine_native_resources.aladin_object_hovered(object.data);
                }
            });            // Update on user move of view
            aladin.on('positionChanged', function(pos) {
              if (pos) {
                  //console.log('View moved to ' + pos.ra*degToHours + ' ' + pos.dec);
                  var tempcoords = (pos.ra*degToHours).toFixed(5) + " " + (pos.dec).toFixed(5);
                  if (engine_params.isRepositionModeFunc != null
                        && engine_params.isRepositionModeFunc()
                        && tempcoords != aladin_position
                        && aladin_view_ready)
                    {
                        aladin_position = tempcoords;
                        image_target = tempcoords;
                        aladin_view_ready = false;
                        get_image_target_ra_dec();
                        EngineViewGrid(true);
                        engine_params.repositionTargetFunc(image_target);
                  }
              }
              else {
                //not sure if there is a fail condition here
              }
          });
        }
        return aladin;
    }

    function createMosaicTableElement(txt)
    {
        var tabdata = document.createElement("TD");
        var celltext = document.createTextNode(txt);
        tabdata.style.border = "1px solid #dddddd";
        tabdata.style.padding = "4px";
        tabdata.appendChild(celltext);
        return tabdata;
    }

    function amISOdatestring(amdate)
    {
        var amdatestr = toDateString(amdate.getUTCFullYear()) + "-" + toDateString(amdate.getUTCMonth()+1) + "-" + toDateString(amdate.getUTCDate()) + " " +
                        toDateString(amdate.getUTCHours()) + ":" + toDateString(amdate.getUTCMinutes());
        if (!engine_params.timezoneOffset) {
            amdatestr += ' UTC';
        } else {
            amdatestr += ' TZ' + engine_params.timezoneOffset;
        }
        return amdatestr;
    }

    function EngineViewGrid(reposition)
    {
        var grid_size_x;
        var grid_size_y;

        console.log('EngineViewGrid');

        grid_size_x = engine_params.grid_size_x;
        grid_size_y = engine_params.grid_size_y;

        if (grid_size_x == 1 && grid_size_y == 1 && grid_type != "visual") {
            grid_type = "fov";
        }
        if (grid_type == "mosaic") {
            var size_x = grid_size_x / 2 - 0.5;
            var size_y = grid_size_y / 2 - 0.5;
        } else {
            var size_x = 1;
            var size_y = 1;
            grid_size_x = 3;
            grid_size_y = 3;
        }

        // Show image and get coordinates from there to
        // calculate grid boxes.
        if (grid_type == "mosaic") {
            if (grid_size_x > grid_size_y) {
                aladin_fov = (grid_size_x+0.2)*Math.max(engine_params.am_fov_x, engine_params.am_fov_y)*aladin_fov_extra;
            } else {
                aladin_fov = (grid_size_y+0.2)*Math.max(engine_params.am_fov_x, engine_params.am_fov_y)*aladin_fov_extra;
            }
        } else {
            aladin_fov = 1.2*Math.max(engine_params.am_fov_x, engine_params.am_fov_y)*aladin_fov_extra;
        }

        if (reposition) {
            engine_data.aladin.removeLayers();
            addAladinCatalogs(engine_data.aladin, true);
        } else {
            engine_data.aladin = EngineInitAladin(aladin_fov, image_target);
        }

        var radec = null;
        if (engine_data.aladin) {
            radec = engine_data.aladin.getRaDec();
        }

        console.log("center RaDec = ", radec);

        var ra = radec[0];
        var dec = radec[1];

        var x;
        var y;
        var row = size_y;
        var col;
        var panel_radec = [];
        for (x = 0; x < grid_size_x; x++) {
            panel_radec[x] = [];
        }
        y = 0;
        while (row >= -size_y) {
            var row_dec = dec + row * img_fov * engine_params.am_fov_y;
            col = size_x;
            x = 0;
            while (col >= -size_x) {
                var col_ra = ra + col * (img_fov * engine_params.am_fov_x * (1/Math.cos(degrees_to_radians(Math.abs(row_dec)))));

                // now center ra/dec is col_ra/row_dec
                // calculate corners
                var row_dec1 = row_dec + engine_params.am_fov_y/2;
                var row_dec2 = row_dec - engine_params.am_fov_y/2;
                var col_ra1 = ra + col * (img_fov * engine_params.am_fov_x * (1/Math.cos(degrees_to_radians(Math.abs(row_dec1)))));
                var col_ra2 = ra + col * (img_fov * engine_params.am_fov_x * (1/Math.cos(degrees_to_radians(Math.abs(row_dec2)))));
                var col_ra1_delta = ((engine_params.am_fov_x/2) * (1/Math.cos(degrees_to_radians(Math.abs(row_dec1)))));
                var col_ra2_delta = ((engine_params.am_fov_x/2) * (1/Math.cos(degrees_to_radians(Math.abs(row_dec2)))));

                var panel = [
                    [col_ra1-col_ra1_delta, row_dec1], 
                    [col_ra1+col_ra1_delta, row_dec1], 
                    [col_ra2+col_ra2_delta, row_dec2], 
                    [col_ra2-col_ra2_delta, row_dec2], 
                    [col_ra1-col_ra1_delta, row_dec1]
                ];

                var line_color = 'White';

                if (grid_type == "visual") {
                    if (x == 1 && y == 1) {
                        // Add a circle to represent the 60 degree radius
                        var radius = 45;
                        var overlay = A.graphicOverlay({color: 'white', lineWidth: 1, name: radius + ' degrees'});
                        engine_data.aladin.addOverlay(overlay);
                        overlay.add(A.circle(ra, dec, radius, {color: 'white'}));
                    }
                } else if ((grid_type == "mosaic" || (x == 1 && y == 1)) && engine_data.aladin) {
                    let overlay = A.graphicOverlay({color: line_color, lineWidth: 2, name: 'FoV'});
                    engine_data.aladin.addOverlay(overlay);
                    overlay.add(A.polyline(panel, {color: line_color, lineWidth: 2, name: 'FoV'}));
                }
                col = col - 1;

                var col_ra_hours = col_ra * degToHours;

                if (grid_type == "mosaic" || grid_type == "visual") {
                    if (engine_params.current_telescope_service == null ||
                        engine_params.current_telescope_service.radec_format == 0) 
                    {
                        panel_radec[x][y] = col_ra_hours.toFixed(5) + 
                                            " " + row_dec.toFixed(5);
                    } else {
                        panel_radec[x][y] = reformat_coordinates(
                                                col_ra_hours.toFixed(5) + " " + row_dec.toFixed(5));
                    }
                } else {
                    /* We show only one scope FoV (default) so show
                    * coordinates in different formats.
                    */
                    panel_radec[x][y] = "RA/DEC " + 
                                        col_ra_hours.toFixed(5) + " " + row_dec.toFixed(5) + ", d " + 
                                        ra.toFixed(5) + " " + dec.toFixed(5) + ", " +
                                        image_target;
                }
                x = x + 1;
            }
            row = row - 1;
            y = y + 1;
        }
        if (grid_type == "mosaic") {
            if (engine_panels.aladin_panel_text) {
                document.getElementById(engine_panels.aladin_panel_text).innerHTML = panel_radec[1][1];
                var tab = document.createElement("TABLE");
                tab.style.width = "100%";
                tab.style.borderCollapse="collapse";
                var tabrow = document.createElement("TR");
                tab.appendChild(tabrow);
                var tabdata = createMosaicTableElement("");
                tabrow.appendChild(tabdata);
                var colnames = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
                for (var x = 0; x < grid_size_x; x++) {
                    var tabdata = createMosaicTableElement(colnames[x]);
                    tabrow.appendChild(tabdata);
                }
                for (var y = 0; y < grid_size_y; y++) {
                    var tabrow = document.createElement("TR");
                    tab.appendChild(tabrow);
                    var tabdata = createMosaicTableElement(y+1);
                    tabrow.appendChild(tabdata);
                    for (var x = 0; x < grid_size_x; x++) {
                        var tabdata = createMosaicTableElement(panel_radec[x][y]);
                        tabrow.appendChild(tabdata);
                    }
                }
                document.getElementById(engine_panels.aladin_panel_text).innerHTML = "";
                document.getElementById(engine_panels.aladin_panel_text).appendChild(tab);
            }
        } else {
            if (engine_view_type == "all" || engine_view_type == "embedded") {
                document.getElementById(engine_panels.aladin_panel_text).innerHTML = panel_radec[1][1];
            } else if (engine_panels.aladin_panel_text) {
                document.getElementById(engine_panels.aladin_panel_text).style.marginTop = "1px";
                document.getElementById(engine_panels.aladin_panel_text).innerHTML = engine_params.astro_mosaic_link;
            }
        }
        if (engine_view_type == "all") {
            /* Add moon and optionally planet path to the Aladin view */
            var midday = engine_params.UTCdate_ms + day_ms/2;
            var interval = 60*60*1000; // 60 minutes
            var draw_full_day = 1;  // if 0 draw only during astronomical twilight
            if (draw_full_day) {
                if (engine_params.grid_type == "visual" && engine_params.UTCdatetime_ms != null) {
                    var starttime = engine_params.UTCdatetime_ms;
                } else {
                    var starttime = midday - engine_params.timezoneOffset * 3600 * 1000;
                }
                var endtime = starttime + day_ms;
            } else {
                var suntimes = sun_rise_set(midday, engine_params.location_lat, engine_params.location_lng, -12);
                var starttime = suntimes.sunset - suntimes.sunset % interval;
                var endtime = suntimes.sunrise + interval - suntimes.sunrise % interval;
            }
            var moonpath = [];
            var moonsources = [];
            for (var d = starttime; d <= endtime; d = d + interval) {
                var moonpos = moon_position(d);
                moonpath.push([moonpos.ra, moonpos.dec]);
                var moonpathinfo = [];
                for (var d2 = d; d2 < d + interval; d2 = d2 + 10*60*1000) { // every 10 minutes
                    var moonpos2 = moon_position(d2);
                    var pathdate = new Date(d2 + engine_params.timezoneOffset * 3600 * 1000);
                    var radec_str = (moonpos2.ra * degToHours).toFixed(5) + ' ' + moonpos2.dec.toFixed(5);
                    moonpathinfo.push([amISOdatestring(pathdate), radec_str, reformat_coordinates(radec_str)]);
                }
                if (d != engine_params.UTCdate_now_ms) {
                    var moondate = new Date(d + engine_params.timezoneOffset * 3600 * 1000);
                    var radec_str = (moonpos.ra * degToHours).toFixed(5) + ' ' + moonpos.dec.toFixed(5);
                    moonsources.push(A.source(moonpos.ra, moonpos.dec, 
                                    { name: 'Moon, ' + amISOdatestring(moondate) + 
                                            ', RA/DEC ' +  radec_str + ', ' + reformat_coordinates(radec_str),
                                      pathname: 'Moon',
                                      pathinfo: moonpathinfo }));
                    }
            }

            // Add path
            console.log("Add moon path, len " + moonpath.length);
            let moonoverlay = A.graphicOverlay({color: '#1c91c0', lineWidth: 2, name: 'Moon line'});
            engine_data.aladin.addOverlay(moonoverlay);
            moonoverlay.add(A.polyline(moonpath, {color: '#1c91c0', lineWidth: 2, name: 'Moon line'}));

            // Add catalog with clickable/hoverable objects
            var cat = A.catalog({sourceSize: 20, shape: 'circle', color: '#1c91c0', name: 'Moon' });
            engine_data.aladin.addCatalog(cat);
            cat.addSources(moonsources);
        
            if (starttime <= engine_params.UTCdate_now_ms && endtime >= engine_params.UTCdate_now_ms) {
                // current time is within the path
                var moonpos = moon_position(engine_params.UTCdate_now_ms);
                var moonsources = [];
                var moonposinfo = [];
                for (var d2 = engine_params.UTCdate_now_ms; d2 < engine_params.UTCdate_now_ms + interval; d2 = d2 + 10*60*1000) { // every 10 minutes
                    var moonpos2 = moon_position(d2);
                    var pathdate = new Date(d2 + engine_params.timezoneOffset * 3600 * 1000);
                    moonposinfo.push([amISOdatestring(pathdate), (moonpos2.ra * degToHours).toFixed(5) + ' ' + moonpos2.dec.toFixed(5)]);
                }
                var moondate = new Date(engine_params.UTCdate_now_ms + engine_params.timezoneOffset * 3600 * 1000);
                var radec_str = (moonpos.ra * degToHours).toFixed(5) + ' ' + moonpos.dec.toFixed(5);
                moonsources.push(A.source(moonpos.ra, moonpos.dec,
                                { name: 'Moon now, ' + amISOdatestring(moondate) +
                                        ', RA/DEC ' +  radec_str + ', ' + reformat_coordinates(radec_str),
                                    pathname: 'Moon now',
                                    pathinfo: moonposinfo }));
                var cat = A.catalog({sourceSize: 28, shape: 'circle', color: '#1c91c0', name: 'Moon now' });
                engine_data.aladin.addCatalog(cat);
                cat.addSources(moonsources);
            }

            if (engine_params.planet_id != null) {
                // planets move slowly so print four weeks of path
                if (engine_params.UTCdatetime_ms != null) {
                    var starttime = engine_params.UTCdatetime_ms;
                } else {
                    var starttime = engine_params.UTCdate_ms;
                }
                var endtime = starttime + 4*7*day_ms;
                var interval = 12*60*60*1000; // 12 hours
                var planetpath = [];
                var planetsources = [];
                for (var d = starttime; d <= endtime; d = d + interval) {
                    var planetpos = planet_position(d, planets[engine_params.planet_id]);
                    planetpath.push([planetpos.ra, planetpos.dec]);
                    var planetpathinfo = [];
                    for (var d2 = d; d2 < d + interval; d2 = d2 + 60*60*1000) { // every 60 minutes
                        var planetpos2 = planet_position(d2, planets[engine_params.planet_id]);
                        var pathdate = new Date(d2 + engine_params.timezoneOffset * 3600 * 1000);
                        var radec_str = (planetpos2.ra * degToHours).toFixed(5) + ' ' + planetpos2.dec.toFixed(5);
                        planetpathinfo.push([amISOdatestring(pathdate), radec_str, reformat_coordinates(radec_str)]);
                    }
                    if (d != engine_params.UTCdate_now_ms) {
                        var planetdate = new Date(d + engine_params.timezoneOffset * 3600 * 1000);
                        var radec_str = (planetpos.ra * degToHours).toFixed(5) + ' ' + planetpos.dec.toFixed(5);
                        planetsources.push(A.source(planetpos.ra, planetpos.dec, 
                                            { name: planets[engine_params.planet_id].name + ', ' + amISOdatestring(planetdate) + 
                                                    ', RA/DEC ' + radec_str + ', ' + reformat_coordinates(radec_str),
                                            pathname: planets[engine_params.planet_id].name,
                                            pathinfo: planetpathinfo }));
                    }
                }
                // Add path
                console.log("Add planet path, len " + planetpath.length);
                let planetoverlay = A.graphicOverlay({color: 'Magenta', lineWidth: 2, name: planets[engine_params.planet_id].name + ' line'});
                engine_data.aladin.addOverlay(planetoverlay);
                planetoverlay.add(A.polyline(planetpath, {color: 'Magenta', lineWidth: 2, name: planets[engine_params.planet_id].name + ' line'}));

                // Add catalog with clickable/hoverable objects
                var cat = A.catalog({sourceSize: 10, shape: 'circle', color: 'Magenta', name: planets[engine_params.planet_id].name });
                engine_data.aladin.addCatalog(cat);
                cat.addSources(planetsources);

                if (starttime <= engine_params.UTCdate_now_ms && endtime >= engine_params.UTCdate_now_ms) {
                    // current time is within the path
                    var planetpos = planet_position(engine_params.UTCdate_now_ms, planets[engine_params.planet_id]);
                    var planetsources = [];
                    var planetposinfo = [];
                    for (var d2 = engine_params.UTCdate_now_ms; d2 < engine_params.UTCdate_now_ms + interval; d2 = d2 + 60*60*1000) { // every 60 minutes
                        var planetpos2 = planet_position(d2, planets[engine_params.planet_id]);
                        var pathdate = new Date(d2 + engine_params.timezoneOffset * 3600 * 1000);
                        planetposinfo.push([amISOdatestring(pathdate), (planetpos2.ra * degToHours).toFixed(5) + ' ' + planetpos2.dec.toFixed(5)]);
                    }
                    var planetdate = new Date(engine_params.UTCdate_now_ms + engine_params.timezoneOffset * 3600 * 1000);
                    var radec_str = (planetpos.ra * degToHours).toFixed(5) + ' ' + planetpos.dec.toFixed(5);
                    planetsources.push(A.source(planetpos.ra, planetpos.dec,
                                       { name: planets[engine_params.planet_id].name + ' now, ' + amISOdatestring(planetdate) +
                                            ', RA/DEC ' + radec_str + ', ' + reformat_coordinates(radec_str),
                                         pathname: planets[engine_params.planet_id].name + ' now',
                                         pathinfo: planetposinfo }));
                    var cat = A.catalog({sourceSize: 18, shape: 'circle', color: 'Magenta', name: planets[engine_params.planet_id].name + ' now' });
                    engine_data.aladin.addCatalog(cat);
                    cat.addSources(planetsources);
                }
            }
        }
        aladin_view_ready = true; 
    }

    function EngineViewGridFromList(coordinates)
    {
        console.log('EngineViewGridFromList');

        var grid_size = coordinates.length;

        // Show image and get coordinates from there to
        // calculate grid boxes.
        var aladin_fov;
        if (engine_params.am_fov_x > engine_params.am_fov_y) {
            aladin_fov = (grid_size+0.2)*engine_params.am_fov_x;
        } else {
            aladin_fov = (grid_size+0.2)*engine_params.am_fov_y;
        }

        engine_data.aladin = EngineInitAladin(aladin_fov, coordinates[0]);
        var radec = null;

        console.log("center RaDec = ", coordinates[0]);

        for (var i = 0; i < coordinates.length; i++) {
            radec = get_ra_dec(coordinates[i]);
            var col_ra = radec[0];
            var row_dec = radec[1];

            console.log("panel "+i+" ra/dec=", col_ra, "/", row_dec);

            // calculate corners
            drawBox(col_ra, row_dec, engine_params.am_fov_x, engine_params.am_fov_y, 'FoV');
        }
    }

    function drawBox(col_ra, row_dec, fov_x, fov_y, name)
    {
        console.log('drawBox', col_ra, row_dec, fov_x, fov_y);

        // calculate image corners
        var row_dec1 = row_dec + fov_y/2;
        var row_dec2 = row_dec - fov_y/2;
        var col_ra1 = col_ra;
        var col_ra2 = col_ra;
        var col_ra1_delta = ((fov_x/2) * (1/Math.cos(degrees_to_radians(Math.abs(row_dec1)))));
        var col_ra2_delta = ((fov_x/2) * (1/Math.cos(degrees_to_radians(Math.abs(row_dec2)))));

        var panel = [
            [col_ra1-col_ra1_delta, row_dec1], 
            [col_ra1+col_ra1_delta, row_dec1], 
            [col_ra2+col_ra2_delta, row_dec2], 
            [col_ra2-col_ra2_delta, row_dec2], 
            [col_ra1-col_ra1_delta, row_dec1]
        ];

        if (name == 'FoV') {
            var line_color = 'White';
        } else {
            var line_color = '#ee2345';
        }
        if (engine_data.aladin) {
            var overlay = A.graphicOverlay({color: line_color, lineWidth: 2, name: name});
            engine_data.aladin.addOverlay(overlay);
            overlay.add(A.polyline(panel, {color: line_color, lineWidth: 2, name: name}));
        }
    }

    // Show telescope Fov and offaxis guiding FoV
    // https://ruuth.xyz/AstroMosaic.html?set_service=Fuji%20X-T3,400mm,206,137,60.04298,24.24452,tz:2,weather:detect_location&add_offaxis=Fuji%20X-T3,400mm,2,2,1,T
    function EngineViewGridOffaxis()
    {
        console.log('EngineViewGridOffaxis');

        var total_fov_x = engine_params.am_fov_x + engine_params.offaxis.am_fov_x;
        var total_fov_y = engine_params.am_fov_y;

        // Show image and get coordinates from there to
        // calculate grid boxes.
        var aladin_fov = 1.2*Math.max(total_fov_x, total_fov_y)*aladin_fov_extra;

        engine_data.aladin = EngineInitAladin(aladin_fov, image_target);
        var radec = null;

        console.log("center RaDec = ", image_target);

        radec = get_ra_dec(image_target);
        var col_ra = radec[0];
        var row_dec = radec[1];

        console.log("ra/dec=", col_ra, "/", row_dec);

        // telescope FoV
        drawBox(col_ra, row_dec, engine_params.am_fov_x, engine_params.am_fov_y, 'FoV');

        // offaxis guiding FoV
        switch (engine_params.offaxis.position) {
            case 'T':
                drawBox(
                    col_ra, 
                    row_dec + engine_params.am_fov_y/2 + engine_params.offaxis.am_offset + engine_params.offaxis.am_fov_y/2,
                    engine_params.offaxis.am_fov_x, 
                    engine_params.offaxis.am_fov_y,
                    'Offaxis');
                break;
            case 'B':
                drawBox(
                    col_ra, 
                    row_dec - engine_params.am_fov_y/2 - engine_params.offaxis.am_offset - engine_params.offaxis.am_fov_y/2,
                    engine_params.offaxis.am_fov_x, 
                    engine_params.offaxis.am_fov_y,
                    'Offaxis');
                break;
            case 'L':
                drawBox(
                    col_ra + 
                        (engine_params.am_fov_x/2 + engine_params.offaxis.am_offset + engine_params.offaxis.am_fov_x/2) *
                        (1/Math.cos(degrees_to_radians(Math.abs(row_dec)))), 
                    row_dec,
                    engine_params.offaxis.am_fov_x, 
                    engine_params.offaxis.am_fov_y,
                    'Offaxis');
                break;
            case 'R':
                drawBox(
                    col_ra - 
                        (engine_params.am_fov_x/2 + engine_params.offaxis.am_offset + engine_params.offaxis.am_fov_x/2) *
                        (1/Math.cos(degrees_to_radians(Math.abs(row_dec)))),
                    row_dec,
                    engine_params.offaxis.am_fov_x, 
                    engine_params.offaxis.am_fov_y,
                    'Offaxis');
                break;
        }

        var col_ra_hours = col_ra * degToHours;
        panel_radec = "RA/DEC " + 
            col_ra_hours.toFixed(5) + " " + row_dec.toFixed(5) + ", " + 
            col_ra.toFixed(5) + " " + row_dec.toFixed(5) + ", " +
            image_target;

        document.getElementById(engine_panels.aladin_panel_text).innerHTML = panel_radec;
    }

    function EngineViewMosaicPanels()
    {
        console.log('EngineViewMosaicPanels');

        var grid_size_x = engine_params.grid_size_x;
        var grid_size_y = engine_params.grid_size_y;
        if (grid_size_x == 1 && grid_size_y == 1) {
            EngineViewGrid(false);
            return;
        }
        if (grid_size_x > engine_panels.catalog_panel_x) {
            document.getElementById(engine_panels.error_text).innerHTML = build_error_text("Max size in panels view is 5x5");
            grid_size_x = engine_panels.catalog_panel_x;
        }
        if (grid_size_y > engine_panels.catalog_panel_y) {
            document.getElementById(engine_panels.error_text).innerHTML = build_error_text("Max size in panels view is 5x5");
            grid_size_y = engine_panels.catalog_panel_y;
        }

        engine_native_resources.reset_view();

        var size_x = grid_size_x / 2 - 0.5;
        var size_y = grid_size_y / 2 - 0.5;

        console.log("image_target=" + image_target);
        var ra = target_ra;
        var dec = target_dec;

        var i = 0;
        var row = size_y;
        var col;
        var row_number = 0;
        var y = 0;
        while (row >= -size_y) {
            var row_dec = dec + row * img_fov * engine_params.am_fov_y;
            col = size_x;
            var panel_number = 5 * row_number;
            var x = 0;
            while (col >= -size_x) {
                var col_ra = ra + col * (img_fov * engine_params.am_fov_x * (1/Math.cos(degrees_to_radians(Math.abs(row_dec)))));
                // convert from degrees to hours
                col_ra = col_ra * degToHours;

                var point_ra_hour = Math.floor(col_ra);
                var point_ra_sec = (Math.abs(col_ra) - Math.abs(point_ra_hour)) * 3600;
                var point_ra_min = Math.floor(point_ra_sec / 60);
                point_ra_sec = point_ra_sec - point_ra_min * 60;
        
                var point_dec_hour = Math.floor(row_dec);
                var point_dec_sec = (Math.abs(row_dec) - Math.abs(point_dec_hour)) * 3600;
                var point_dec_min = Math.floor(point_dec_sec / 60);
                point_dec_sec = point_dec_sec - point_dec_min * 60;
        
                var aladin_target_str = point_ra_hour.toString() + ":" + point_ra_min.toString() + ":" + point_ra_sec.toFixed(2) + " ";
                var aladin_target_str = aladin_target_str + point_dec_hour.toString() + ":" + point_dec_min.toString() + ":" + point_dec_sec.toFixed(2);

                var panel_id = engine_panels.panel_view_div + y.toString() + x.toString();
                console.log('EngineViewMosaicPanels, panel_id='+panel_id);
                if (engine_params.am_fov_x != engine_params.am_fov_y) {
                    var height = 300 * engine_params.am_fov_y / engine_params.am_fov_x;
                    document.getElementById(panel_id).style.height = Math.floor(height).toString() + "px";
                } else {
                    document.getElementById(panel_id).style.height = "300px";
                }
                if (A) {
                    engine_data.aladinarr[i] = A.aladin('#'+panel_id, {survey: "P/DSS2/color", fov:engine_params.am_fov_x, target: aladin_target_str,
                                                showReticle:false, showZoomControl:false, showFullscreenControl:false, 
                                                showLayersControl:false, showGotoControl:false,
                                                showControl: false, cooFrame: "J2000", showFrame: false});
                }
                document.getElementById(engine_panels.panel_view_text+y.toString()+x.toString()).innerHTML = (i+1).toString() + " RA/DEC " + col_ra.toFixed(5) + " " + row_dec.toFixed(5);
                col = col - 1;
                i = i + 1;
                panel_number = panel_number + 1;
                x = x + 1;
            }
            row = row - 1;
            row_number = row_number + 1;
            y = y + 1;
        }
    }

    /* View targets from JSON list.
     * Example: { "targets": [ { "radec": "19.89624 18.77917", "name": "M71" }, { "radec": "12.38192  15.82228", "name": "M100" } ] }
     */
    function EngineViewTargetPanels(target_json)
    {
        console.log('EngineViewTargetPanels');

        if (!target_json) {
            console.log('EngineViewTargetPanels failed to parse target json');
            return;
        }

        var target_list = target_json.targets;
        if (target_list.length == 0) {
            console.log('EngineViewTargetPanels empty target list');
            return;
        }

        engine_native_resources.reset_view();

        var x = 0;
        var y = 0;

        for (var i = 0; i < target_list.length; i++) {
            console.log('EngineViewTargetPanels radec:' + target_list[i].radec);
            var radec = reformat_coordinates(target_list[i].radec);

            console.log('EngineViewTargetPanels reformat_coordinates:', radec);

            var panel_id = engine_panels.panel_view_div + y.toString() + x.toString();
            console.log('EngineViewTargetPanels, panel_id='+panel_id);
            if (engine_params.am_fov_x != engine_params.am_fov_y) {
                var height = 300 * engine_params.am_fov_y / engine_params.am_fov_x;
                document.getElementById(panel_id).style.height = Math.floor(height).toString() + "px";
            } else {
                document.getElementById(panel_id).style.height = "300px";
            }
            if (A) {
                engine_data.aladinarr[i] = A.aladin('#'+panel_id, {survey: "P/DSS2/color", fov:engine_params.am_fov_x, target: radec,
                                            showReticle:false, showZoomControl:false, showFullscreenControl:false, 
                                            showLayersControl:false, showGotoControl:false,
                                            showControl: false, cooFrame: "J2000", showFrame: false});
            }
            document.getElementById(engine_panels.panel_view_text+y.toString()+x.toString()).innerHTML = target_list[i].name + "<br>" +
                                                                                                         " RA/DEC " + radec;
            x = x + 1;
            if (x >= engine_panels.catalog_panel_x) {
                x = 0;
                y = y + 1;
            }
            if (y >= engine_panels.catalog_panel_y) {
                break;
            }
        }
        while (y < engine_panels.catalog_panel_y) {
            document.getElementById(engine_panels.panel_view_div+y.toString()+x.toString()).innerHTML = "";
            document.getElementById(engine_panels.panel_view_text+y.toString()+x.toString()).innerHTML = "";
            x = x + 1;
            if (x >= engine_panels.catalog_panel_x) {
                x = 0;
                y = y + 1;
            }
        }
    }
}
