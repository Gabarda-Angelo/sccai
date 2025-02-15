<?php
header('Content-Type: application/json');
include_once 'connectdb.php';

try {
    // Validate input parameters
    if(isset($_GET['barcode'])) {
        $searchType = 'barcode';
        $searchValue = (string)$_GET['barcode'];
        $query = "SELECT *, CAST(barcode AS CHAR) AS barcode_str 
                 FROM products WHERE barcode = :search";
    } elseif(isset($_GET['id'])) {
        $searchType = 'id';
        $searchValue = (int)$_GET['id'];
        $query = "SELECT * FROM products WHERE product_id = :search";
    } else {
        throw new Exception("Missing search parameter");
    }

    // Prepare and execute query
    $stmt = $pdo->prepare($query);
    $stmt->bindParam(':search', $searchValue);
    $stmt->execute();
    $result = $stmt->fetch(PDO::FETCH_ASSOC);

    if(!$result) {
        throw new Exception("Product not found");
    }

    // Format numeric values
    $result['product_id'] = (int)$result['product_id'];
    $result['stock'] = (int)$result['stock'];
    $result['sale_price'] = (float)$result['sale_price'];
    $result['purchase_price'] = (float)$result['purchase_price'];

    // Handle barcode string conversion
    if(isset($result['barcode_str'])) {
        $result['barcode'] = $result['barcode_str'];
        unset($result['barcode_str']);
    }

    echo json_encode($result);

} catch(PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'Database error: ' . $e->getMessage()]);
} catch(Exception $e) {
    http_response_code(404);
    echo json_encode(['error' => $e->getMessage()]);
}
?>