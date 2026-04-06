// scripts/generate-manifest.js
// Run this script in your project root to generate a manifest of your summary files

const fs = require('fs');
const path = require('path');

const summariesDir = path.join(__dirname, '..', 'src', 'assets', 'summaries');
const manifestPath = path.join(summariesDir, 'manifest.json');

function generateManifest() {
  try {
    // Create summaries directory if it doesn't exist
    if (!fs.existsSync(summariesDir)) {
      fs.mkdirSync(summariesDir, { recursive: true });
      console.log('Created summaries directory:', summariesDir);
    }

    // Read all files in the summaries directory
    const files = fs.readdirSync(summariesDir)
      .filter(file => file.endsWith('.json') && file !== 'manifest.json')
      .sort(); // Sort alphabetically

    // Generate manifest
    const manifest = {
      generated: new Date().toISOString(),
      files: files,
      count: files.length,
      patterns: {
        deepseek: files.filter(f => f.startsWith('deepseek')).length,
        claude: files.filter(f => f.startsWith('claude')).length,
        other: files.filter(f => !f.startsWith('deepseek') && !f.startsWith('claude')).length
      }
    };

    // Write manifest file
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    
    console.log('✅ Manifest generated successfully!');
    console.log(`📁 Found ${files.length} summary files`);
    console.log(`📊 Breakdown: ${manifest.patterns.deepseek} DeepSeek, ${manifest.patterns.claude} Claude, ${manifest.patterns.other} Other`);
    console.log(`📄 Manifest saved to: ${manifestPath}`);
    
    if (files.length === 0) {
      console.log('⚠️  No summary files found. Make sure to place your JSON files in src/assets/summaries/');
    } else {
      console.log('\n📋 Files included:');
      files.forEach(file => console.log(`   - ${file}`));
    }

  } catch (error) {
    console.error('❌ Error generating manifest:', error.message);
  }
}

// Also provide a simple file list version for the service
function generateSimpleManifest() {
  try {
    const files = fs.readdirSync(summariesDir)
      .filter(file => file.endsWith('.json') && file !== 'manifest.json')
      .sort();

    const simpleManifest = files;
    const simpleManifestPath = path.join(summariesDir, 'file-list.json');
    
    fs.writeFileSync(simpleManifestPath, JSON.stringify(simpleManifest, null, 2));
    console.log(`📄 Simple file list saved to: ${simpleManifestPath}`);
    
    return simpleManifest;
  } catch (error) {
    console.error('❌ Error generating simple manifest:', error.message);
    return [];
  }
}

if (require.main === module) {
  console.log('🔧 Generating manifest for parliamentary summaries...\n');
  generateManifest();
  generateSimpleManifest();
}

module.exports = { generateManifest, generateSimpleManifest };
