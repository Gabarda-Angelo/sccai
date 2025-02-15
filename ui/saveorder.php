<?php
include_once 'connectdb.php';
session_start();

header('Content-Type: application/json');

try {
    if (!isset($_SESSION['employee_id'])) {
        throw new Exception("Unauthorized access");
    }

    $pdo->beginTransaction();

    // Insert invoice
    $stmt = $pdo->prepare("
        INSERT INTO invoices (
            employee_id, order_date, order_time, 
            subtotal, discount, total, 
            paid, due, payment_type, promotion_id
        ) VALUES (
            :employee_id, CURDATE(), CURTIME(), 
            :subtotal, :discount, :total, 
            :paid, :due, :payment_type, :promotion_id
        )
    ");
    
    $stmt->execute([
        ':employee_id' => $_SESSION['employee_id'],
        ':subtotal' => $_POST['txtsubtotal'],
        ':discount' => $_POST['discount'],
        ':total' => $_POST['txttotal'],
        ':paid' => $_POST['txtpaid'],
        ':due' => $_POST['txtdue'],
        ':payment_type' => $_POST['rb'],
        ':promotion_id' => $_POST['promotion_id'] ?: null
    ]);
    
    $invoice_id = $pdo->lastInsertId();

    // Insert order items
    foreach ($_POST['pid_arr'] as $index => $product_id) {
        // Update stock
        $update = $pdo->prepare("
            UPDATE products 
            SET stock = stock - :qty 
            WHERE product_id = :product_id
        ");
        $update->execute([
            ':qty' => $_POST['quantity_arr'][$index],
            ':product_id' => $product_id
        ]);

        // Insert detail
        $stmt = $pdo->prepare("
            INSERT INTO invoice_details (
                invoice_id, product_id, 
                quantity, unit_price, total_price
            ) VALUES (
                :invoice_id, :product_id, 
                :quantity, :unit_price, :total_price
            )
        ");
        $stmt->execute([
            ':invoice_id' => $invoice_id,
            ':product_id' => $product_id,
            ':quantity' => $_POST['quantity_arr'][$index],
            ':unit_price' => $_POST['price_c_arr'][$index],
            ':total_price' => $_POST['saleprice_arr'][$index]
        ]);
    }

    $pdo->commit();
    
    echo json_encode([
        'success' => true,
        'invoice_id' => $invoice_id,
        'total' => $_POST['txttotal']
    ]);

} catch(Exception $e) {
    $pdo->rollBack();
    http_response_code(500);
    echo json_encode([
        'success' => false,
        'error' => $e->getMessage()
    ]);
}