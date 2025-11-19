// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    const button = document.getElementById('testButton');
    const output = document.getElementById('output');
    
    button.addEventListener('click', async function() {
        output.textContent = 'Loading...';
        
        try {
            // Example: Call your API to get users
            const response = await fetch('/users/');
            const data = await response.json();
            
            output.textContent = `Found ${data.users.length} users!`;
        } catch (error) {
            output.textContent = 'Error: ' + error.message;
        }
    });
});