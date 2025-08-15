// Concentric Rings Radial Profile Analysis Macro
// Uses ImageJ's native ROI capabilities for reliable measurements
// Usage: 1) Open image 2) Select rectangular ROI around point source 3) Run macro

macro "Concentric Rings Profile" {
    // Check if an image is open
    if (nImages == 0) {
        showMessage("Error", "Please open an image first");
        exit();
    }
    
    // Check if ROI is selected
    if (selectionType() != 0) {  // 0 = rectangle
        showMessage("Error", "Please select a rectangular ROI first");
        exit();
    }
    
    // Get image info
    imageTitle = getTitle();
    imageID = getImageID();
    getPixelSize(unit, pixelWidth, pixelHeight);
    
    // Parameter dialog
    Dialog.create("Concentric Rings Parameters");
    Dialog.addNumber("Maximum Radius (" + unit + "):", 30);
    Dialog.addNumber("Ring Width (" + unit + "):", 2);
    Dialog.addNumber("Median Filter Radius (pixels, 0=off):", 2);
    Dialog.addCheckbox("Show Ring ROIs", true);
    Dialog.addMessage("Analysis will measure average intensity in concentric rings");
    Dialog.show();
    
    maxRadius = Dialog.getNumber();
    ringWidth = Dialog.getNumber();
    filterRadius = Dialog.getNumber();
    showRings = Dialog.getCheckbox();
    
    // Get ROI bounds and calculate center
    getBoundingRect(roiX, roiY, roiWidth, roiHeight);
    centerX = roiX + roiWidth / 2;
    centerY = roiY + roiHeight / 2;
    
    // Calculate number of rings
    numRings = floor(maxRadius / ringWidth);
    
    // Create working image
    selectImage(imageID);
    run("Select None");
    
    // Apply median filter if specified
    if (filterRadius > 0) {
        run("Duplicate...", "title=temp_filtered");
        run("Median...", "radius=" + filterRadius);
        workingID = getImageID();
    } else {
        workingID = imageID;
    }
    
    // Initialize results arrays
    ringCenters = newArray(numRings);
    ringIntensities = newArray(numRings);
    ringAreas = newArray(numRings);
    ringCounts = newArray(numRings);
    
    // Convert center coordinates and ring parameters to pixels
    centerXpix = centerX;
    centerYpix = centerY;
    maxRadiusPix = maxRadius / pixelWidth;
    ringWidthPix = ringWidth / pixelWidth;
    
    print("Processing concentric rings...");
    print("Center: (" + centerX + ", " + centerY + ")");
    print("Max radius: " + maxRadius + " " + unit + " (" + maxRadiusPix + " pixels)");
    print("Ring width: " + ringWidth + " " + unit + " (" + ringWidthPix + " pixels)");
    print("Number of rings: " + numRings);
    
    // Clear ROI Manager
    if (isOpen("ROI Manager")) {
        selectWindow("ROI Manager");
        run("Close");
    }
    run("ROI Manager...");
    
    // Process each ring
    for (i = 0; i < numRings; i++) {
        // Calculate ring boundaries in pixels
        innerRadius = i * ringWidthPix;
        outerRadius = (i + 1) * ringWidthPix;
        
        // Calculate ring center distance in actual units
        ringCenters[i] = (innerRadius + outerRadius) / 2 * pixelWidth;
        
        selectImage(workingID);
        
        // Create outer circle
        outerX = centerXpix - outerRadius;
        outerY = centerYpix - outerRadius;
        outerWidth = outerRadius * 2;
        outerHeight = outerRadius * 2;
        
        makeOval(outerX, outerY, outerWidth, outerHeight);
        
        if (i == 0) {
            // First ring is just the inner circle
            if (showRings) {
                roiManager("Add");
                roiManager("Select", 0);
                roiManager("Rename", "Ring_" + (i+1));
            }
            
            // Measure
            run("Measure");
            ringIntensities[i] = getResult("Mean", nResults-1);
            ringAreas[i] = getResult("Area", nResults-1);
            
        } else {
            // For other rings, subtract inner circle from outer circle
            if (showRings) {
                roiManager("Add");
                roiManager("Select", i);
                roiManager("Rename", "Ring_" + (i+1) + "_outer");
            }
            
            // Create inner circle
            innerX = centerXpix - innerRadius;
            innerY = centerYpix - innerRadius;
            innerWidth = innerRadius * 2;
            innerHeight = innerRadius * 2;
            
            makeOval(innerX, innerY, innerWidth, innerHeight);
            
            if (showRings) {
                roiManager("Add");
                roiManager("Select", roiManager("Count")-1);
                roiManager("Rename", "Ring_" + (i+1) + "_inner");
                
                // Select both ROIs and combine
                roiManager("Select", newArray(roiManager("Count")-2, roiManager("Count")-1));
                roiManager("XOR");
                roiManager("Add");
                roiManager("Select", roiManager("Count")-1);
                roiManager("Rename", "Ring_" + (i+1));
                
                // Clean up temporary ROIs
                roiManager("Select", newArray(roiManager("Count")-3, roiManager("Count")-2));
                roiManager("Delete");
            } else {
                // Create ring by XOR without saving intermediate ROIs
                roiManager("Add");  // Add inner circle temporarily
                roiManager("Select", newArray(roiManager("Count")-2, roiManager("Count")-1));
                roiManager("XOR");
                roiManager("Delete");  // Remove temporary inner circle
            }
            
            // Measure the ring
            run("Measure");
            ringIntensities[i] = getResult("Mean", nResults-1);
            ringAreas[i] = getResult("Area", nResults-1);
        }
        
        // Calculate approximate pixel count
        ringCounts[i] = ringAreas[i] / (pixelWidth * pixelHeight);
        
        // Show progress
        showProgress(i, numRings);
    }
    
    // Clean up temporary image
    if (filterRadius > 0) {
        selectImage(workingID);
        close();
    }
    
    // Create results table
    if (isOpen("Ring Profile Results")) {
        selectWindow("Ring Profile Results");
        run("Close");
    }
    
    run("New... ", "name=[Ring Profile Results] type=Table");
    print("[Ring Profile Results]", "\\Headings:Ring\tDistance_" + unit + "\tMean_Intensity\tArea_" + unit + "2\tPixel_Count");
    
    for (i = 0; i < numRings; i++) {
        print("[Ring Profile Results]", (i+1) + "\t" + ringCenters[i] + "\t" + ringIntensities[i] + "\t" + ringAreas[i] + "\t" + ringCounts[i]);
    }
    
    // Create plot
    Plot.create("Concentric Rings Profile - " + imageTitle, "Distance (" + unit + ")", "Mean Intensity");
    Plot.setFrameSize(600, 400);
    Plot.add("line", ringCenters, ringIntensities);
    Plot.add("circle", ringCenters, ringIntensities);
    Plot.setStyle(0, "blue,#a0a0ff,2.0");
    Plot.setStyle(1, "blue,blue,5.0");
    Plot.setLimits(0, maxRadius, NaN, NaN);
    Plot.show();
    
    // Add center point marker on original image
    selectImage(imageID);
    makePoint(centerXpix, centerYpix);
    run("Add Selection...");
    
    print("Analysis complete!");
    print("Center: (" + centerX + ", " + centerY + ")");
    print("Rings analyzed: " + numRings);
    print("Ring width: " + ringWidth + " " + unit);
    print("Total radius: " + (numRings * ringWidth) + " " + unit);
    
    // Clean up Results table
    if (isOpen("Results")) {
        selectWindow("Results");
        run("Close");
    }
}

// Simplified version for batch processing
macro "Quick Rings Profile" {
    // Check requirements
    if (nImages == 0) {
        showMessage("Error", "Please open an image first");
        exit();
    }
    
    if (selectionType() != 0) {
        showMessage("Error", "Please select a rectangular ROI first");
        exit();
    }
    
    // Use default parameters
    maxRadius = 30;      // microns
    ringWidth = 2;       // microns
    filterRadius = 2;    // pixels
    
    // Get image info
    imageTitle = getTitle();
    imageID = getImageID();
    getPixelSize(unit, pixelWidth, pixelHeight);
    
    // Get center from ROI
    getBoundingRect(roiX, roiY, roiWidth, roiHeight);
    centerX = roiX + roiWidth / 2;
    centerY = roiY + roiHeight / 2;
    
    // Calculate number of rings
    numRings = floor(maxRadius / ringWidth);
    
    // Apply median filter
    run("Select None");
    run("Duplicate...", "title=temp_filtered");
    run("Median...", "radius=" + filterRadius);
    workingID = getImageID();
    
    // Initialize arrays
    ringCenters = newArray(numRings);
    ringIntensities = newArray(numRings);
    
    // Convert to pixels
    centerXpix = centerX;
    centerYpix = centerY;
    ringWidthPix = ringWidth / pixelWidth;
    
    print("Quick processing: " + numRings + " rings, " + ringWidth + " " + unit + " width");
    
    // Clear ROI Manager
    if (isOpen("ROI Manager")) {
        selectWindow("ROI Manager");
        run("Close");
    }
    run("ROI Manager...");
    
    // Process rings
    for (i = 0; i < numRings; i++) {
        innerRadius = i * ringWidthPix;
        outerRadius = (i + 1) * ringWidthPix;
        ringCenters[i] = (innerRadius + outerRadius) / 2 * pixelWidth;
        
        selectImage(workingID);
        
        // Create outer circle
        makeOval(centerXpix - outerRadius, centerYpix - outerRadius, 
                 outerRadius * 2, outerRadius * 2);
        
        if (i == 0) {
            run("Measure");
            ringIntensities[i] = getResult("Mean", nResults-1);
        } else {
            roiManager("Add");
            makeOval(centerXpix - innerRadius, centerYpix - innerRadius, 
                     innerRadius * 2, innerRadius * 2);
            roiManager("Add");
            roiManager("Select", newArray(roiManager("Count")-2, roiManager("Count")-1));
            roiManager("XOR");
            run("Measure");
            ringIntensities[i] = getResult("Mean", nResults-1);
            roiManager("Delete");
        }
        
        showProgress(i, numRings);
    }
    
    // Clean up
    selectImage(workingID);
    close();
    
    // Create simple results
    if (isOpen("Quick Ring Results")) {
        selectWindow("Quick Ring Results");
        run("Close");
    }
    
    run("New... ", "name=[Quick Ring Results] type=Table");
    print("[Quick Ring Results]", "\\Headings:Distance_" + unit + "\tIntensity");
    
    for (i = 0; i < numRings; i++) {
        print("[Quick Ring Results]", ringCenters[i] + "\t" + ringIntensities[i]);
    }
    
    // Simple plot
    Plot.create("Quick Rings - " + imageTitle, "Distance (" + unit + ")", "Mean Intensity");
    Plot.add("line", ringCenters, ringIntensities);
    Plot.show();
    
    print("Quick analysis complete: " + numRings + " rings processed");
    
    // Clean up
    if (isOpen("Results")) {
        selectWindow("Results");
        run("Close");
    }
    if (isOpen("ROI Manager")) {
        selectWindow("ROI Manager");
        run("Close");
    }
}

// Helper macro for parameter setup
macro "Set Ring Parameters" {
    // Get current image units if available
    if (nImages > 0) {
        getPixelSize(unit, pixelWidth, pixelHeight);
        unitLabel = " (" + unit + ")";
    } else {
        unitLabel = "";
    }
    
    Dialog.create("Set Ring Analysis Parameters");
    Dialog.addNumber("Maximum Radius" + unitLabel + ":", 30);
    Dialog.addNumber("Ring Width" + unitLabel + ":", 2);
    Dialog.addNumber("Median Filter Radius (pixels):", 2);
    Dialog.addMessage("Parameters for concentric ring analysis");
    Dialog.addMessage("Ring width determines resolution of radial profile");
    Dialog.addMessage("Smaller ring width = higher resolution but more rings");
    Dialog.show();
    
    maxRadius = Dialog.getNumber();
    ringWidth = Dialog.getNumber();
    filterRadius = Dialog.getNumber();
    
    numRings = floor(maxRadius / ringWidth);
    
    print("Ring Parameters Set:");
    print("Max Radius: " + maxRadius + unitLabel);
    print("Ring Width: " + ringWidth + unitLabel);
    print("Filter Radius: " + filterRadius + " pixels");
    print("Number of rings: " + numRings);
    print("Total analysis radius: " + (numRings * ringWidth) + unitLabel);
    
    if (numRings > 50) {
        print("Warning: " + numRings + " rings will be created. Consider increasing ring width for faster processing.");
    }
}