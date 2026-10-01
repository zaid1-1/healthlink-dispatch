// constraints so MERGE doesn't create duplicates
CREATE CONSTRAINT FOR (h:TraumaCenter) REQUIRE h.hospital_id IS UNIQUE
CREATE CONSTRAINT FOR (z:IncidentZone) REQUIRE z.name IS UNIQUE

// the 12 hospitals
MERGE (:TraumaCenter {hospital_id: 1, name: 'Al Bashir Hospital'})
MERGE (:TraumaCenter {hospital_id: 2, name: 'Jordan University Hospital'})
MERGE (:TraumaCenter {hospital_id: 3, name: 'King Hussein Medical Center'})
MERGE (:TraumaCenter {hospital_id: 4, name: 'Istishari Hospital'})
MERGE (:TraumaCenter {hospital_id: 5, name: 'Prince Hamzah Hospital'})
MERGE (:TraumaCenter {hospital_id: 6, name: 'Al Khalidi Hospital'})
MERGE (:TraumaCenter {hospital_id: 7, name: 'Farah Hospital'})
MERGE (:TraumaCenter {hospital_id: 8, name: 'Zarqa Governmental Hospital'})
MERGE (:TraumaCenter {hospital_id: 9, name: 'Princess Basma Hospital'})
MERGE (:TraumaCenter {hospital_id: 10, name: 'Arab Medical Center'})
MERGE (:TraumaCenter {hospital_id: 11, name: 'Prince Rashid Hospital'})
MERGE (:TraumaCenter {hospital_id: 12, name: 'Queen Alia Heart Institute'})

// the 6 zones
MERGE (:IncidentZone {name: 'Abdoun'})
MERGE (:IncidentZone {name: 'Jabal Amman'})
MERGE (:IncidentZone {name: 'Sweifieh'})
MERGE (:IncidentZone {name: 'Marka'})
MERGE (:IncidentZone {name: 'Zarqa'})
MERGE (:IncidentZone {name: 'Abdali'})

// zone to hospital roads, run one at a time
MATCH (z:IncidentZone {name: 'Abdoun'}), (h:TraumaCenter {hospital_id: 1})
MERGE (z)-[:ROAD_TO {distance_km: 5.5}]-(h)

MATCH (z:IncidentZone {name: 'Abdoun'}), (h:TraumaCenter {hospital_id: 6})
MERGE (z)-[:ROAD_TO {distance_km: 3.0}]-(h)

MATCH (z:IncidentZone {name: 'Jabal Amman'}), (h:TraumaCenter {hospital_id: 10})
MERGE (z)-[:ROAD_TO {distance_km: 1.5}]-(h)

MATCH (z:IncidentZone {name: 'Sweifieh'}), (h:TraumaCenter {hospital_id: 4})
MERGE (z)-[:ROAD_TO {distance_km: 2.5}]-(h)

MATCH (z:IncidentZone {name: 'Marka'}), (h:TraumaCenter {hospital_id: 3})
MERGE (z)-[:ROAD_TO {distance_km: 2.0}]-(h)

MATCH (z:IncidentZone {name: 'Marka'}), (h:TraumaCenter {hospital_id: 5})
MERGE (z)-[:ROAD_TO {distance_km: 3.5}]-(h)

MATCH (z:IncidentZone {name: 'Zarqa'}), (h:TraumaCenter {hospital_id: 8})
MERGE (z)-[:ROAD_TO {distance_km: 2.0}]-(h)

MATCH (z:IncidentZone {name: 'Abdali'}), (h:TraumaCenter {hospital_id: 2})
MERGE (z)-[:ROAD_TO {distance_km: 6.0}]-(h)

// roads connecting the hospitals to each other so the whole graph is reachable
MATCH (h1:TraumaCenter {hospital_id: 1}), (h2:TraumaCenter {hospital_id: 6})
MERGE (h1)-[:ROAD_TO {distance_km: 3.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 6}), (h2:TraumaCenter {hospital_id: 10})
MERGE (h1)-[:ROAD_TO {distance_km: 1.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 10}), (h2:TraumaCenter {hospital_id: 7})
MERGE (h1)-[:ROAD_TO {distance_km: 2.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 7}), (h2:TraumaCenter {hospital_id: 4})
MERGE (h1)-[:ROAD_TO {distance_km: 3.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 4}), (h2:TraumaCenter {hospital_id: 2})
MERGE (h1)-[:ROAD_TO {distance_km: 7.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 2}), (h2:TraumaCenter {hospital_id: 3})
MERGE (h1)-[:ROAD_TO {distance_km: 8.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 3}), (h2:TraumaCenter {hospital_id: 5})
MERGE (h1)-[:ROAD_TO {distance_km: 2.5}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 3}), (h2:TraumaCenter {hospital_id: 12})
MERGE (h1)-[:ROAD_TO {distance_km: 1.0}]-(h2)

// zarqa and irbid don't have a zone nearby so they only connect through here
MATCH (h1:TraumaCenter {hospital_id: 1}), (h2:TraumaCenter {hospital_id: 8})
MERGE (h1)-[:ROAD_TO {distance_km: 25.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 8}), (h2:TraumaCenter {hospital_id: 9})
MERGE (h1)-[:ROAD_TO {distance_km: 60.0}]-(h2)

MATCH (h1:TraumaCenter {hospital_id: 9}), (h2:TraumaCenter {hospital_id: 11})
MERGE (h1)-[:ROAD_TO {distance_km: 3.0}]-(h2)

// referral relationships
MATCH (h1:TraumaCenter {hospital_id: 1}), (h2:TraumaCenter {hospital_id: 12})
MERGE (h1)-[:REFERS_TO {specialty: 'Cardiology'}]->(h2)

MATCH (h1:TraumaCenter {hospital_id: 8}), (h2:TraumaCenter {hospital_id: 3})
MERGE (h1)-[:REFERS_TO {specialty: 'Trauma Surgery'}]->(h2)


// quick test - shortest path from abdoun to irbid hospital
MATCH p = shortestPath(
  (z:IncidentZone {name: 'Abdoun'})-[:ROAD_TO*..10]-(h:TraumaCenter {hospital_id: 9})
)
RETURN p

// quick test - who al bashir refers patients to
MATCH (h:TraumaCenter {name: 'Al Bashir Hospital'})-[:REFERS_TO]->(specialist)
RETURN specialist.name, specialist.hospital_id
