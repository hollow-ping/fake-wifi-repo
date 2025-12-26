/* 
  main.js - Shared JavaScript
  
  LocalStorage logic + small scripts
  
  The login cookie is simply the burnerName - no other status tracking needed.
  
  Keys:
  - tempBurnerName: Temporary storage during account creation (before captchas complete)
  - burnerName: The actual "cookie" - only set after completing account creation (captchas)
  
  Flow:
  1. User enters username → saved to tempBurnerName
  2. User completes password → tempBurnerName persists
  3. User completes captchas → tempBurnerName → burnerName (cookie committed)
  4. Login checks only burnerName (not tempBurnerName)
  
  Device States:
  1. New Device (no burnerName) → Full flow
  2. Has Account (has burnerName) → Can login with burnerName
*/

// Check device state and redirect accordingly
function checkDeviceState() {
    // If user has burnerName (cookie), they can login
    // But we still show the create account button for new users
    const burnerName = localStorage.getItem("burnerName");
    
    if (burnerName) {
        // User has account - they can login
        // But don't auto-redirect, let them choose
        return "hasAccount";
    }
    
    // New device - show create account button
    return "newDevice";
}

// Get the stored burner name (the "cookie")
// Only returns committed burnerName, not tempBurnerName
function getBurnerName() {
    return localStorage.getItem("burnerName") || "User";
}

// Set burner name (this is the "cookie" - just the username)
// Note: This will overwrite any existing burnerName if user creates a new account
function setBurnerName(name) {
    localStorage.setItem("burnerName", name);
}

// Temporary burner name during account creation (before captchas complete)
// Note: This automatically overwrites any existing tempBurnerName if user goes back and creates new account
function setTempBurnerName(name) {
    localStorage.setItem("tempBurnerName", name);
}

function getTempBurnerName() {
    return localStorage.getItem("tempBurnerName");
}

// Commit temp burner name to actual cookie after completing account creation
// Note: This overwrites any existing burnerName (if user creates new account)
function commitBurnerName() {
    const tempName = getTempBurnerName();
    if (tempName) {
        setBurnerName(tempName); // Commit to cookie (overwrites existing if any)
        localStorage.removeItem("tempBurnerName"); // Clear temp
        return tempName;
    }
    return null;
}

// Get burner name during account creation (checks temp first, then committed)
function getBurnerNameDuringCreation() {
    return getTempBurnerName() || getBurnerName() || "User";
}

// Check if user has an account (has burnerName cookie - not temp)
function hasAccount() {
    return localStorage.getItem("burnerName") !== null;
}
