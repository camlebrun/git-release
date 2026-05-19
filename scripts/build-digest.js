import { S3Client, ListObjectsV2Command, GetObjectCommand } from '@aws-sdk/client-s3'
import { execSync } from 'child_process'
import { writeFileSync, mkdirSync } from 'fs'
import { resolve } from 'path'
import * as dotenv from 'dotenv'

dotenv.config({ path: '.env.local' })

function getSecret(name) {
  if (process.env[name]) return process.env[name]
  return execSync(
    `gcloud secrets versions access latest --secret=${name} --project=git-release-496817`,
    { encoding: 'utf8' }
  ).trim()
}

const accountId     = getSecret('R2_ACCOUNT_ID')
const accessKeyId   = getSecret('R2_ACCESS_KEY_ID')
const secretKey     = getSecret('R2_SECRET_ACCESS_KEY')
const BUCKET        = 'git-release-releases'

const s3 = new S3Client({
  region: 'auto',
  endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
  credentials: { accessKeyId, secretAccessKey: secretKey },
})

async function streamToString(stream) {
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  return Buffer.concat(chunks).toString('utf8')
}

async function main() {
  console.log('📦 Listing R2 objects...')
  const keys = []
  let token

  do {
    const res = await s3.send(new ListObjectsV2Command({
      Bucket: BUCKET, Prefix: 'releases/', ContinuationToken: token
    }))
    for (const obj of res.Contents ?? []) keys.push(obj.Key)
    token = res.NextContinuationToken
  } while (token)

  console.log(`  → ${keys.length} releases found`)

  const records = []
  let done = 0

  await Promise.all(
    keys.map(async key => {
      try {
        const res = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: key }))
        const raw = JSON.parse(await streamToString(res.Body))
        if (!raw.analysis) return   // skip un-analysed
        delete raw.body             // strip raw markdown
        records.push(raw)
        process.stdout.write(`\r  ✓ ${++done}/${keys.length}`)
      } catch (e) {
        console.warn(`\n  ⚠ ${key}: ${e.message}`)
      }
    })
  )

  records.sort((a, b) => (b.published_at ?? '').localeCompare(a.published_at ?? ''))

  mkdirSync('public', { recursive: true })
  const out = resolve('public/digest.json')
  writeFileSync(out, JSON.stringify(records, null, 2))
  console.log(`\n✅ ${records.length} records → public/digest.json`)
}

main().catch(err => { console.error(err); process.exit(1) })
