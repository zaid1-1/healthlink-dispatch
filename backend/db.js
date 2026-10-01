require("dotenv").config();
const oracledb = require("oracledb");
const { MongoClient } = require("mongodb");
const neo4j = require("neo4j-driver");

oracledb.outFormat = oracledb.OUT_FORMAT_OBJECT;

async function initOraclePool() {
  oraclePool = await oracledb.createPool({
    user: process.env.ORACLE_USER,
    password: process.env.ORACLE_PASSWORD,
    connectString: process.env.ORACLE_DSN,
    poolMin: 1,
    poolMax: 4,
    poolIncrement: 1,
  });
  console.log("Oracle pool ready");
}

async function getOracleConnection() {
  return oraclePool.getConnection();
}

function getMongoClient() {
  return new MongoClient(process.env.MONGO_URI);
}

function getNeo4jDriver() {
  return neo4j.driver(
    process.env.NEO4J_URI,
    neo4j.auth.basic(process.env.NEO4J_USER, process.env.NEO4J_PASSWORD)
  );
}

const MONGO_DB_NAME = process.env.MONGO_DB_NAME;

module.exports = {
  initOraclePool,
  getOracleConnection,
  getMongoClient,
  getNeo4jDriver,
  MONGO_DB_NAME,
  oracledb,
};