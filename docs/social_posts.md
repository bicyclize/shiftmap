# Social posts — bike-train analysis tool

**EN = LinkedIn · HU = Facebook.** Numbers current as of 2026-10-26.
The tool is always framed as *"could be done"*, never *"was done"*, and Élhető Főutak is always a *concept*, never a *programme*.

---

## Post 1 — the reframe

**EN**

**I built a cycling and bike-train propensity tool...**

I started posting images of what main roads in Budapest could look like. My hypothesis: follow Sevilla/Paris lead, build a network of quick build protective cycle paths. Remove one lane, adjust potentially junctions to improve traffic flow. 
I got a lot of critique. The additional travel time for car drivers does not justify for some, the opportunity of having a brand new transport mode in the city, which on the other hand could reduce the number of cars. "But nobody cycles here!" - they say. 

"How many people cycle in your city?" tells you almost nothing about how to get *more* people cycling. The question that actually matters: **which car trips could already be a bike — or a bike and a train?**

So I built a tool that answers it from real GPS traces. One week of Budapest: ~19,000 unique devices a day, 390,000 car trips in total. The result: **44% of all trips were shorter than 5 km** — physically a bike ride. Another ~45,000 could be bike-to-station-and-bike again, ~28,000 bike-to-station-and-walk.

But thats too vague, we need exact locations, to see where to appraise infrastructure first: where are these trips? 
So I projected these on to a map, you can zoom in, select areas or street segments, and it filters out the trips that start/end or just pass here (BTW something LTNs could also utilise)!

**So do we need 2 lanes on a given corridor?** 
From the 5200 trips on this main road in Budapest, almost 10% are under 5km (bikeride), another 35% (yes, 1800 trips) could have been covered by bike+train+bike and another 23% simply by bike+train+foot. Only 2000! of the total trips needed really a car!

Of course, there are caveats of trip times, GTFS timetables, carrying the piano and grandma at the same time, which is a recurring justification for car use, but it clearly shows that there is latent demand to use alternatives for cars, should those exist!

Interested in a similar tool for your borough, town, city, country? Catch me at Smart City Expo World Congress next week in Barcelona! Ill show you in action. 

#activemobility #cycling #urbanmobility #biketrain





**HU**

Posztoltam párat arról, hogy nézhetnének ki Budapest főútjai, ha a sevillai és párizsi mintát követnénk: gyorsan, olcsón megépíthető, védett bicikliutak hálózatát hoznánk létre. Egy forgalmisávot átadnánk a bicikliseknek, a kereszteződéseket pedig megigazítanánk, hogy javítsuk az áteresztőképességet.

Persze, sok kritikát kaptam. Van, aki szerint az a pár perc, amivel többet kell autózni, nem éri meg egy teljesen új közlekedési lehetőség kialakítását a városban — pedig épp az csökkentené az autók számát, az meg a dugók megszűnését. „De itt senki sem biciklizik!" — szokták mondani.

Csakhogy a „hányan bicikliznek nálunk?" szinte semmit nem mond arról, hogyan lehetne több kerékpározó. A valódi kérdés: melyik autóval megtett utat lehetne már ma is biciklivel — vagy biciklivel és vonattal — megtenni?

Ezért építettem egy eszközt, ami valós GPS-adatokból kiszámolja ezt. Egy hét Budapesten: napi ~19 ezer telefon, összesen 440 ezer megtett út. Az eredmény: az utak 44%-a 5 km-nél rövidebb volt — ezt simán le lehet tekerni. Még ~45 ezer utat lehetett volna bicikli + vonat + biciklivel megtenni, ~28 ezret pedig bicikli + vonat + gyalog.

De ez így túl általános. Pontosan tudni akarom, hol vannak ezek az utak, hogy lássuk, hova érdemes először bicikliutat építeni. Ezért feltettem őket egy térképre: rá lehet nagyítani, ki lehet jelölni egy területet vagy egy utcát, és az eszköz megmutatja, mely utak indulnak ott, érkeznek oda, vagy csak átmennek rajta. (Ezt egyébként a forgalomcsillapított lakóövezeteknél is lehetne használni.)

Szóval kell-e egy főúton két autósáv? Egy budapesti külső Váci úton az 5200 mért útból közel 10% 5 km alatti volt — le lehet tekerni. Újabb 35% (igen, 1800 út) mehetett volna bicikli + vonat + bicikli kombinációval, és még 23% bicikli + vonat + gyalog. Az 5200 útból csak 2000-hez kellett volna igazán autó!

Persze vannak további kérdések: a menetrendek, az utazási idő, vagy amikor egyszerre viszed a zongorát és a nagymamát — ez a klasszikus érv az autó mellett. De a számok így is világosan mutatják: ha létezne biciklis lehetőség, sokan élnének vele.

Érdekelne egy ilyen eszköz a te kerületedre, városodra?

#bringa #aktívmobilitás #kerékpár-vasút


---

## Post 2 — data integrity (the loop that wasn't a road)

**EN**

The map showed a loop that made no sense. It turned out to be a service tunnel between two metro lines.

You only catch that kind of error if you refuse to cut corners. My bike–train tool reconstructs every trip as a *routed* path — never a straight line between two dots. It builds a separate cycling network that prefers cycleways and refuses streets marked `bicycle=no`. It draws rail legs only on passenger lines, not depot tracks. And it says its own limits out loud: underground metro is under-detected (no GPS in tunnels), a bus looks identical to a car, and a 1% sample can't support city-wide mode-share claims — so it makes relative, spatial ones instead.

The result is a map you can defend in front of a room full of engineers: where latent cycling demand actually sits, not a pretty chart of made-up numbers.

*#gis #dataforgood #transportplanning #opensource*

**HU**

A térképen volt egy hurok, aminek semmi értelme nem volt. Kiderült, hogy két metróvonal közötti üzemi összekötő vágány.

Ilyen hibát csak akkor veszel észre, ha nem vágsz kanyarokat. A bringa-vonat eszközöm minden utat valódi *útvonalként* épít fel — soha nem két pont közötti egyenesként. Külön kerékpáros hálózatot épít, ami a kerékpárutakat részesíti előnyben, és elutasítja a „kerékpárral behajtani tilos" utcákat. A vonatos szakaszokat csak utasszállító vonalakon rajzolja, nem a depóvágányokon. És hangosan kimondja a saját korlátait: a földalatti metró alul-detektált (nincs GPS az alagútban), a busz megkülönböztethetetlen az autótól, és egy 1%-os minta nem bír el városi modális megosztást — ezért inkább relatív, térbeli állításokat tesz.

Az eredmény egy olyan térkép, amit mérnökök előtt is meg tudsz védeni: hol van valójában a lappangó kerékpáros kereslet, nem egy szép ábra kitalált számokról.

*#gis #adatok #közlekedéstervezés #nyíltforráskód*

---

## Post 3 — data is only useful if it ends in asphalt

**EN**

Data is only useful if it ends in asphalt.

The point of my bike–train tool isn't a dashboard — it's a shortlist. Because every alternative trip is a *calculated route*, the output isn't "44% could cycle"; it's "**these five streets, and these station catchments, carry most of the opportunity**". That's the difference between a statistic and a place to put a temporary protected lane.

Two steps follow: (1) find who could switch, (2) put temporary infrastructure on the multi-lane roads where they'd ride — the idea behind Budapest's Liveable Main Roads concept. Low-cost, reversible, testable in weeks, not years.

If you plan streets, ask this question first.

*#tacticalurbanism #streetdesign #cyclinginfrastructure #liveablestreets*

**HU**

Az adat csak akkor ér valamit, ha a végén aszfalt lesz belőle.

A bringa-vonat eszközöm értelme nem egy dashboard — hanem egy shortlist. Mivel minden alternatív út *kiszámított útvonal*, a kimenet nem „a 44% bringázhatna", hanem „**ez az öt utca, és ezek az állomáskörzetek viszik a lehetőség nagy részét**". Ez a különbség egy statisztika és egy hely között, ahová ideiglenes védett sávot tehetsz.

Ebből két lépés következik: (1) találd meg, ki válthatna, (2) tegyél ideiglenes infrastruktúrát azokra a többsávos utakra, ahol tekernének — ez az Élhető Főutak koncepció alapja. Olcsó, visszafordítható, hetek alatt tesztelhető, nem évek.

Ha utcákat tervezel, először ezt a kérdést tedd fel.

*#taktikaiurbanizmus #utcatervezés #kerékpárosinfrastruktúra #ÉlhetőFőutak*

---

## Post 4 — low-traffic neighbourhoods (LTN)

**EN**

Traffic-calming usually starts with a guess about who's actually driving through a neighbourhood. It doesn't have to.

The tool that finds bike-and-train trips answers the low-traffic-neighbourhood question too: draw a street or an area, and it tells you what share of the traffic is local versus cut-through — and, of the cut-through, what share is short trips that could just as easily be a bike.

That's the argument an LTN actually needs: you're not "banning cars", you're stopping other people's shortcuts from using your street. And it's measurable before a single bollard goes in.

Find who's passing through, show what could shift, then build. In that order.

*#lowtrafficneighbourhood #LTN #trafficcalming #streetsforpeople*

**HU**

A forgalomcsillapítás általában találgatással kezdődik arról, hogy ki hajt át valójában egy lakónegyeden. Nem kellene.

Ugyanaz az eszköz, ami a bringa-vonat utakat megtalálja, a low-traffic kérdésre is válaszol: rajzold körbe az utcát vagy a területet, és megmutatja, a forgalom mekkora része helyi, és mekkora az átmenő — és az átmenőből mennyi az a rövid út, ami akár bringa is lehetne.

Ez az érv kell egy lakóövezeti forgalomcsillapításhoz: nem autót tiltasz, hanem azt, hogy mások rövidítője a te utcádon menjen át. És ez mérhető, mielőtt az első oszlop a földbe kerül.

Előbb találd meg, ki megy át — aztán mutasd meg, mi válthatna — utána építs. Ebben a sorrendben.

*#lowtrafficneighbourhood #forgalomcsillapítás #utcákazembereknek #lakóövezet*
